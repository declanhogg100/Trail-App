import geopandas as gpd
import requests
from pyproj import Geod
from shapely.geometry import LineString, MultiLineString

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Overpass blocks requests carrying the default python-requests User-Agent
# (an anti-bot measure, observed as a generic Apache 406) -- any non-default
# value works, so this is set to something clearly identifying this project
HEADERS = {"User-Agent": "trail-app-recommender/0.1"}

_GEOD = Geod(ellps="WGS84")


def build_hiking_relations_query(bbox: tuple[float, float, float, float]) -> str:
    west, south, east, north = bbox
    # Overpass QL's own bbox filter order is (south, west, north, east) --
    # different from the (west, south, east, north) convention used
    # elsewhere in this project, kept explicit here to avoid a repeat mixup
    return f"""
    [out:json][timeout:180];
    (
      relation["route"="hiking"]({south},{west},{north},{east});
    );
    (._;>;);
    out geom;
    """


def fetch_hiking_relations(bbox: tuple[float, float, float, float]) -> dict:
    query = build_hiking_relations_query(bbox)
    response = requests.post(OVERPASS_URL, data={"data": query}, headers=HEADERS, timeout=200)
    response.raise_for_status()
    return response.json()


def _member_to_linestring(member: dict) -> LineString | None:
    coords = [(pt["lon"], pt["lat"]) for pt in member.get("geometry", [])]
    if len(coords) < 2:
        return None
    return LineString(coords)


def relations_to_geodataframe(response_json: dict) -> gpd.GeoDataFrame:
    rows = []
    for element in response_json["elements"]:
        if element["type"] != "relation":
            continue
        tags = element.get("tags", {})
        if "name" not in tags:
            continue

        pieces = [
            _member_to_linestring(member)
            for member in element.get("members", [])
            if member.get("type") == "way"
        ]
        pieces = [p for p in pieces if p is not None]
        if not pieces:
            continue

        distance_m = sum(abs(_GEOD.geometry_length(p)) for p in pieces)

        rows.append(
            {
                "osm_id": element["id"],
                "name": tags["name"],
                "distance_m": distance_m,
                "geometry": MultiLineString(pieces),
            }
        )

    return gpd.GeoDataFrame(rows, crs="EPSG:4326")
