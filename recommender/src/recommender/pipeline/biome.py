import geopandas as gpd
from shapely.geometry import Point

ECOREGIONS_PATH = "data/ecoregions.parquet"

_ecoregions: gpd.GeoDataFrame | None = None


def load_ecoregions() -> gpd.GeoDataFrame:
    global _ecoregions
    if _ecoregions is None:
        _ecoregions = gpd.read_parquet(ECOREGIONS_PATH)
    return _ecoregions


# OSM's coastline and the WWF ecoregion polygons' coastline don't perfectly
# agree, so a point that's genuinely on land can sometimes fall just outside
# every polygon. ~0.05 degrees (~5km) is generous enough to bridge that gap
# but still rejects points genuinely out at sea, far from any polygon.
NEAREST_FALLBACK_DEGREES = 0.05


def find_biome(lat: float, lon: float) -> dict:
    ecoregions = load_ecoregions()
    point = Point(lon, lat)
    matches = ecoregions[ecoregions.contains(point)]
    if not matches.empty:
        row = matches.iloc[0]
    else:
        distances = ecoregions.geometry.distance(point)
        nearest_idx = distances.idxmin()
        if distances[nearest_idx] > NEAREST_FALLBACK_DEGREES:
            return {"eco_name": None, "biome_name": None, "realm": None}
        row = ecoregions.loc[nearest_idx]
    return {
        "eco_name": row["eco_name"],
        "biome_name": row["biome_name"],
        "realm": row["realm"],
    }
