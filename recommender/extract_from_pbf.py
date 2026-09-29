import os
import sys

import geopandas as gpd
import osmium
from shapely.geometry import LineString

from recommender.pipeline.osm_trails import _GEOD, _merge_pieces


def extract_relations(pbf_path: str) -> tuple[dict[int, str], dict[int, list[int]]]:
    print("pass 1: scanning relations...")
    fp = osmium.FileProcessor(pbf_path, osmium.osm.RELATION).with_filter(
        osmium.filter.TagFilter(("route", "hiking"))
    )

    relation_name: dict[int, str] = {}
    relation_ways: dict[int, list[int]] = {}

    count = 0
    for rel in fp:
        name = rel.tags.get("name")
        if not name:
            continue
        way_ids = [m.ref for m in rel.members if m.type == "w"]
        if not way_ids:
            continue
        relation_name[rel.id] = name
        relation_ways[rel.id] = way_ids
        count += 1
        if count % 1000 == 0:
            print(f"  ...{count} named hiking relations found so far")

    print(f"pass 1 done: {len(relation_name)} named hiking relations")
    return relation_name, relation_ways


def extract_way_geometries(
    pbf_path: str, needed_way_ids: set[int], cache_path: str
) -> dict[int, LineString]:
    print(f"pass 2: extracting geometry for {len(needed_way_ids)} ways...")
    # NODE must stay included (not just WAY) -- with_locations() caches node
    # coordinates as they stream past, and needs to actually see the node
    # objects to do that before it can resolve them onto ways. IdFilter is
    # scoped to WAY only, so nodes pass through untouched either way.
    #
    # the default in-memory location cache OOM-killed on a whole-country
    # file (this machine has 8GB RAM; a full US extract has 500M+ nodes) --
    # sparse_file_array stores it on disk instead, sized to the nodes
    # actually present (not the full theoretical OSM id range, unlike
    # dense_file_array, which tried to allocate a 48GB file for even the
    # tiny Rhode Island test)
    fp = (
        osmium.FileProcessor(pbf_path, osmium.osm.NODE | osmium.osm.WAY)
        .with_locations(f"sparse_file_array,{cache_path}")
        .with_filter(osmium.filter.IdFilter(needed_way_ids).enable_for(osmium.osm.WAY))
    )

    geometries: dict[int, LineString] = {}
    count = 0
    for obj in fp:
        # NODE objects also stream through here (with_locations() needs to
        # see them to cache coordinates) -- only WAY objects are relevant
        # from this point on
        if obj.type_str() != "w":
            continue
        way = obj
        coords = [(n.lon, n.lat) for n in way.nodes if n.location.valid()]
        if len(coords) >= 2:
            geometries[way.id] = LineString(coords)
        count += 1
        if count % 5000 == 0:
            print(f"  ...{count} ways processed")

    print(f"pass 2 done: {len(geometries)} way geometries extracted")
    return geometries


def assemble_trails(
    relation_name: dict[int, str],
    relation_ways: dict[int, list[int]],
    way_geometries: dict[int, LineString],
) -> gpd.GeoDataFrame:
    print("assembling trails from relation + way data...")
    rows = []
    skipped = 0
    for rel_id, way_ids in relation_ways.items():
        pieces = [way_geometries[w] for w in way_ids if w in way_geometries]
        if not pieces:
            skipped += 1
            continue

        distance_m = sum(abs(_GEOD.geometry_length(p)) for p in pieces)
        try:
            merged_geometry = _merge_pieces(pieces)
        except Exception:
            skipped += 1
            continue

        rows.append(
            {
                "osm_id": rel_id,
                "name": relation_name[rel_id],
                "distance_m": distance_m,
                "geometry": merged_geometry,
            }
        )

    print(f"assembled {len(rows)} trails, skipped {skipped} with no usable geometry")
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


def run(pbf_path: str, output_path: str, cache_path: str) -> None:
    relation_name, relation_ways = extract_relations(pbf_path)

    needed_way_ids: set[int] = set()
    for way_ids in relation_ways.values():
        needed_way_ids.update(way_ids)

    try:
        way_geometries = extract_way_geometries(pbf_path, needed_way_ids, cache_path)
    finally:
        # the location cache is scratch space, tens of GB for a whole-country
        # file -- not worth keeping once this run is done
        if os.path.exists(cache_path):
            os.remove(cache_path)

    trails_gdf = assemble_trails(relation_name, relation_ways, way_geometries)
    trails_gdf.to_parquet(output_path)
    print(f"saved {len(trails_gdf)} trails to {output_path}")


if __name__ == "__main__":
    pbf_path = sys.argv[1]
    output_path = sys.argv[2]
    cache_path = sys.argv[3] if len(sys.argv) > 3 else "/tmp/osm_location_cache.bin"
    run(pbf_path, output_path, cache_path)
