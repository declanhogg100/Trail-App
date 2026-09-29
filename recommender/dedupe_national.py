import geopandas as gpd
from shapely.geometry import LineString, MultiLineString

from recommender.pipeline.osm_trails import _GEOD, _merge_pieces

INPUT_PATH = "data/regions/us_national.parquet"
OUTPUT_PATH = "data/regions/us_national.parquet"


def _pieces_of(geometry) -> list[LineString]:
    if geometry.geom_type == "MultiLineString":
        return list(geometry.geoms)
    return [geometry]


def merge_duplicate_group(group: gpd.GeoDataFrame) -> dict:
    # each row in the group is this same relation, independently assembled
    # from a different state's extract -- each only had a partial subset of
    # the relation's member ways, so their geometries are complementary
    # fragments, not genuinely different trails
    all_pieces = []
    for geometry in group["geometry"]:
        all_pieces.extend(_pieces_of(geometry))

    # two states whose extracts both happen to include the exact same
    # border-crossing way would otherwise have that segment double-counted --
    # dedupe by exact coordinates before merging/measuring
    seen = set()
    unique_pieces = []
    for piece in all_pieces:
        key = tuple(piece.coords)
        if key not in seen:
            seen.add(key)
            unique_pieces.append(piece)

    distance_m = sum(abs(_GEOD.geometry_length(p)) for p in unique_pieces)
    merged_geometry = _merge_pieces(unique_pieces)

    first = group.iloc[0]
    return {
        "osm_id": first["osm_id"],
        "name": first["name"],
        "distance_m": distance_m,
        "geometry": merged_geometry,
    }


if __name__ == "__main__":
    df = gpd.read_parquet(INPUT_PATH)
    print(f"loaded {len(df)} rows")

    duplicated_ids = df[df.duplicated("osm_id", keep=False)]["osm_id"].unique()
    print(f"{len(duplicated_ids)} trails span multiple state extracts, merging...")

    kept_rows = df[~df["osm_id"].isin(duplicated_ids)].to_dict("records")

    merged_rows = []
    failed = []
    for osm_id in duplicated_ids:
        group = df[df["osm_id"] == osm_id]
        try:
            merged_rows.append(merge_duplicate_group(group))
        except Exception as e:
            failed.append((osm_id, group.iloc[0]["name"], f"{type(e).__name__}: {e}"))

    print(f"merged {len(merged_rows)} trails, failed {len(failed)}")
    for osm_id, name, err in failed:
        print(f"  {name} ({osm_id}): {err}")

    result = gpd.GeoDataFrame(kept_rows + merged_rows, crs="EPSG:4326")
    print(f"final: {len(result)} rows, unique osm_ids: {result['osm_id'].nunique()}")
    result.to_parquet(OUTPUT_PATH)
    print(f"saved to {OUTPUT_PATH}")
