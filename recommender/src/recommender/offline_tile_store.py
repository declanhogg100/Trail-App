import threading
from collections import defaultdict
from pathlib import Path

from shapely.geometry import LineString, MultiLineString

from recommender.tile_render import render_trail_tiles

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = _PROJECT_ROOT / "data" / "offline_tile_cache"


class OfflineTileStore:
    def __init__(self, cache_dir: str | Path = CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        # FastAPI runs sync endpoint handlers in a thread pool, and
        # MapLibre requests every visible tile roughly at once -- without a
        # lock here, the first wave of concurrent requests for a trail that
        # hasn't been rendered yet would *each* independently kick off a
        # full redundant render (the whole trail, not just their one
        # tile), serializing under the GIL and making the map appear to
        # load tiles one at a time, slowly, instead of all at once.
        # defaultdict(Lock) means each osm_id gets its own lock, so
        # concurrent requests for *different* trails still don't block
        # each other -- only repeat requests for the same one do.
        self._render_locks: dict[int, threading.Lock] = defaultdict(threading.Lock)
        self._render_locks_guard = threading.Lock()

    def _trail_dir(self, osm_id: int) -> Path:
        return self.cache_dir / str(osm_id)

    def _render_lock(self, osm_id: int) -> threading.Lock:
        with self._render_locks_guard:
            return self._render_locks[osm_id]

    def _ensure_rendered(self, osm_id: int, lines: list[list[list[float]]]) -> None:
        marker = self._trail_dir(osm_id) / "_complete"
        if marker.exists():
            return
        with self._render_lock(osm_id):
            # re-check after acquiring the lock -- another thread may have
            # already finished rendering this trail while we were waiting
            if not marker.exists():
                self._render_and_cache(osm_id, lines)

    def get_manifest(self, osm_id: int, lines: list[list[list[float]]]) -> list[dict]:
        self._ensure_rendered(osm_id, lines)
        trail_dir = self._trail_dir(osm_id)
        return [
            {"z": int(p.parent.parent.name), "x": int(p.parent.name), "y": int(p.stem)}
            for p in trail_dir.glob("*/*/*.png")
        ]

    def get_tile_bytes(self, osm_id: int, z: int, x: int, y: int, lines: list[list[list[float]]]) -> bytes | None:
        # used both by the bulk-download flow (already rendered by
        # get_manifest by the time these are fetched) and by the map
        # fetching tiles live, one at a time, for a trail that was never
        # downloaded ahead of time -- so this renders+caches on demand too,
        # not just serves what's already there
        self._ensure_rendered(osm_id, lines)
        path = self._trail_dir(osm_id) / str(z) / str(x) / f"{y}.png"
        if not path.exists():
            return None
        return path.read_bytes()

    def _render_and_cache(self, osm_id: int, lines: list[list[list[float]]]) -> None:
        pieces = [LineString(line) for line in lines if len(line) >= 2]
        geometry = pieces[0] if len(pieces) == 1 else MultiLineString(pieces)

        tiles = render_trail_tiles(geometry)

        trail_dir = self._trail_dir(osm_id)
        for (z, x, y), img in tiles.items():
            tile_path = trail_dir / str(z) / str(x) / f"{y}.png"
            tile_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(tile_path)

        # written only once every tile has saved successfully -- get_manifest
        # uses this as the "already rendered, safe to serve from cache"
        # signal, so a request that dies partway through doesn't leave a
        # half-populated directory mistaken for a complete one next time
        (trail_dir / "_complete").touch()
