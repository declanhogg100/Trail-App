from pathlib import Path

import geopandas as gpd
import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
GEOMETRIES_PATH = _PROJECT_ROOT / "data" / "trail_geometries.parquet"

MAX_TRAILS_PER_REQUEST = 300


def _lines_from_geometry(geom) -> list[list[list[float]]]:
    pieces = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
    return [[[round(lon, 6), round(lat, 6)] for lon, lat in piece.coords] for piece in pieces]


class TrailGeometryStore:
    def __init__(self, geometries_path: str | Path = GEOMETRIES_PATH):
        self.trails = gpd.read_parquet(geometries_path)
        # bbox bounds pulled out as raw numpy for a fast vectorized overlap
        # test -- avoids a GeoPandas spatial-index build for what's just an
        # axis-aligned rectangle intersection over ~40k rows
        self._minx = self.trails["minx"].to_numpy()
        self._miny = self.trails["miny"].to_numpy()
        self._maxx = self.trails["maxx"].to_numpy()
        self._maxy = self.trails["maxy"].to_numpy()
        self._distance_m = self.trails["distance_m"].to_numpy()
        self._osm_id_to_row = {osm_id: i for i, osm_id in enumerate(self.trails["osm_id"])}

    def markers_in_bbox(
        self,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        max_trails: int = MAX_TRAILS_PER_REQUEST,
    ) -> list[dict]:
        # marker-only listing for the map's overview -- no line geometry at
        # all, just one point per trail, so this stays cheap even when a lot
        # of trails are in view. Full geometry is fetched separately, one
        # trail at a time, only once the rider taps a specific marker
        overlaps = (
            (self._minx <= max_lon)
            & (self._maxx >= min_lon)
            & (self._miny <= max_lat)
            & (self._maxy >= min_lat)
        )
        matched_idx = np.where(overlaps)[0]

        # when more trails are in view than the response budget allows,
        # keep the longest ones -- a view that can't show everyone is more
        # useful highlighting a handful of major, recognizable trails than
        # an arbitrary/alphabetical slice of short ones
        if len(matched_idx) > max_trails:
            order = np.argsort(-self._distance_m[matched_idx])[:max_trails]
            matched_idx = matched_idx[order]

        results = []
        for idx in matched_idx:
            row = self.trails.iloc[idx]
            geom = row["geometry"]
            first_piece = geom.geoms[0] if geom.geom_type == "MultiLineString" else geom
            start_lon, start_lat = first_piece.coords[0]
            results.append(
                {
                    "osm_id": int(row["osm_id"]),
                    "name": row["name"],
                    "distance_m": float(row["distance_m"]),
                    "start": [round(start_lon, 6), round(start_lat, 6)],
                }
            )
        return results

    def get_lines(self, osm_id: int) -> list[list[list[float]]] | None:
        if osm_id not in self._osm_id_to_row:
            return None
        row = self.trails.iloc[self._osm_id_to_row[osm_id]]
        return _lines_from_geometry(row["geometry"])
