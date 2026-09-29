import os
import subprocess
import sys

import geopandas as gpd
import pandas as pd
import requests

STATES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "district-of-columbia", "florida", "georgia",
    "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new-hampshire", "new-jersey", "new-mexico", "new-york", "north-carolina",
    "north-dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
    "rhode-island", "south-carolina", "south-dakota", "tennessee", "texas",
    "utah", "vermont", "virginia", "washington", "west-virginia",
    "wisconsin", "wyoming",
]

GEOFABRIK_URL = "https://download.geofabrik.de/north-america/us/{state}-latest.osm.pbf"
DOWNLOAD_DIR = "data/osm_extract/states"
TRAILS_DIR = "data/regions/us_states"
CACHE_PATH = "/tmp/state_location_cache.bin"
COMBINED_OUTPUT = "data/regions/us_national.parquet"


def download_state(state: str) -> str:
    pbf_path = f"{DOWNLOAD_DIR}/{state}.osm.pbf"
    if os.path.exists(pbf_path):
        print(f"  already downloaded: {pbf_path}")
        return pbf_path

    url = GEOFABRIK_URL.format(state=state)
    print(f"  downloading {url}...")
    response = requests.get(url, stream=True, timeout=300)
    response.raise_for_status()
    with open(pbf_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
    size_mb = os.path.getsize(pbf_path) / 1_000_000
    print(f"  saved {pbf_path} ({size_mb:.0f} MB)")
    return pbf_path


def extract_state(state: str, pbf_path: str) -> str | None:
    output_path = f"{TRAILS_DIR}/{state}.parquet"
    if os.path.exists(output_path):
        print(f"  already extracted: {output_path}")
        return output_path

    result = subprocess.run(
        [sys.executable, "-u", "extract_from_pbf.py", pbf_path, output_path, CACHE_PATH],
        capture_output=False,
    )
    if result.returncode != 0:
        print(f"  FAILED extracting {state} (exit code {result.returncode})")
        return None
    return output_path


if __name__ == "__main__":
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(TRAILS_DIR, exist_ok=True)

    failed_states = []
    for i, state in enumerate(STATES, 1):
        print(f"[{i}/{len(STATES)}] {state}")
        try:
            pbf_path = download_state(state)
            output_path = extract_state(state, pbf_path)
            if output_path is None:
                failed_states.append(state)
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
            failed_states.append(state)
        finally:
            # each state's downloaded PBF is only needed to produce its
            # trails parquet -- no reason to keep 50+ multi-hundred-MB files
            # around afterward
            pbf_path = f"{DOWNLOAD_DIR}/{state}.osm.pbf"
            if os.path.exists(pbf_path):
                os.remove(pbf_path)

    print("---")
    print(f"done: {len(STATES) - len(failed_states)}/{len(STATES)} states succeeded")
    if failed_states:
        print(f"failed: {failed_states}")

    print("combining all state trail files...")
    all_dfs = []
    for state in STATES:
        path = f"{TRAILS_DIR}/{state}.parquet"
        if os.path.exists(path):
            all_dfs.append(gpd.read_parquet(path))

    combined = pd.concat(all_dfs, ignore_index=True)
    combined = gpd.GeoDataFrame(combined, crs="EPSG:4326")
    combined.to_parquet(COMBINED_OUTPUT)
    print(f"saved {len(combined)} total trails to {COMBINED_OUTPUT}")
