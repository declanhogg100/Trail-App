import geopandas as gpd
import requests
from pyproj import Geod
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Overpass blocks requests carrying the default python-requests User-Agent
# (an anti-bot measure, observed as a generic Apache 406) -- any non-default
# value works, so this is set to something clearly identifying this project
HEADERS = {"User-Agent": "trail-app-recommender/0.1"}

_GEOD = Geod(ellps="WGS84")

# comfortably above the ~7m digitization noise observed between endpoints
# that are really the same junction, well below the ~35m+ gaps observed
# between endpoints that are genuinely disconnected (e.g. an untagged
# road-walking connector)
SNAP_TOLERANCE_M = 15.0


def build_hiking_relations_query(bbox: tuple[float, float, float, float]) -> str:
    west, south, east, north = bbox
    
    return f"""
    [out:json][timeout:180];
    relation["route"="hiking"]({south},{west},{north},{east});
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


def _snap_nearby_endpoints(
    pieces: list[LineString], tolerance_m: float = SNAP_TOLERANCE_M
) -> list[LineString]:
    endpoints = []
    for i, piece in enumerate(pieces):
        coords = list(piece.coords)
        endpoints.append(coords[0])
        endpoints.append(coords[-1])

    n = len(endpoints)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        root_x, root_y = find(x), find(y)
        if root_x != root_y:
            parent[root_x] = root_y

    for a in range(n):
        lon1, lat1 = endpoints[a]
        for b in range(a + 1, n):
            lon2, lat2 = endpoints[b]
            _, _, dist = _GEOD.inv(lon1, lat1, lon2, lat2)
            if dist <= tolerance_m:
                union(a, b)

    # representative coordinate per cluster of nearby endpoints -- the
    # first one encountered, arbitrarily, since they're within tolerance
    cluster_coord = {}
    for idx in range(n):
        root = find(idx)
        if root not in cluster_coord:
            cluster_coord[root] = endpoints[idx]

    snapped = []
    for i, piece in enumerate(pieces):
        coords = list(piece.coords)
        coords[0] = cluster_coord[find(2 * i)]
        coords[-1] = cluster_coord[find(2 * i + 1)]
        snapped.append(LineString(coords))

    return snapped


def _merge_pieces(pieces: list[LineString]):
    # exact merge first -- only joins pieces sharing provably identical
    # coordinates, so zero false-positive risk. This does almost all the
    # work (e.g. 364 raw pieces down to 2 for one real test trail).
    merged = linemerge(MultiLineString(pieces))
    if merged.geom_type == "LineString":
        return merged

    # only the small number of pieces left over (typically a handful) go
    # through proximity snapping -- doing this on the raw piece count
    # instead caused false positives on winding trails, since switchback
    # legs can pass close to each other without actually connecting
    remaining = list(merged.geoms)
    snapped = _snap_nearby_endpoints(remaining)
    return linemerge(MultiLineString(snapped))


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
        merged_geometry = _merge_pieces(pieces)

        rows.append(
            {
                "osm_id": element["id"],
                "name": tags["name"],
                "distance_m": distance_m,
                "geometry": merged_geometry,
            }
        )

    return gpd.GeoDataFrame(rows, crs="EPSG:4326")
