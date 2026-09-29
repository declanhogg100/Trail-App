import json

# contiguous US bounds, roughly -- generous margins so nothing gets clipped
WEST, EAST = -125.0, -66.0
SOUTH, NORTH = 24.0, 49.5

# small cells (not the 3-5 degree cells considered initially) specifically to
# bound the worst case: OSM data density varies hugely by region (a dense
# metro area cell can be orders of magnitude bigger than a rural one at the
# same grid size), and the whole point of chunking is avoiding another
# memory/IO thrashing incident like the single whole-country pass hit
CELL_SIZE = 2.0

OUTPUT_DIR = "data/osm_extract/chunks"
CONFIG_PATH = "data/osm_extract/extract_config.json"


def build_config() -> dict:
    extracts = []
    lon = WEST
    while lon < EAST:
        lat = SOUTH
        while lat < NORTH:
            name = f"chunk_{lon:.1f}_{lat:.1f}".replace(".", "p").replace("-", "n")
            extracts.append(
                {
                    "output": f"{name}.osm.pbf",
                    "bbox": [lon, lat, min(lon + CELL_SIZE, EAST), min(lat + CELL_SIZE, NORTH)],
                }
            )
            lat += CELL_SIZE
        lon += CELL_SIZE
    return {"directory": OUTPUT_DIR, "extracts": extracts}


if __name__ == "__main__":
    config = build_config()
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    print(f"{len(config['extracts'])} chunks defined, config saved to {CONFIG_PATH}")
