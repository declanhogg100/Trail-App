import pandas as pd

from recommender.pipeline.biome import find_biome
from recommender.pipeline.elevation import (
    compute_gain_and_grade_stats,
    compute_prominence_features,
    resample_trail,
)
from recommender.pipeline.landcover import compute_tree_cover_pct


def _representative_point(geometry):
    # geometry.centroid is the geometric centroid of the shape, which for a
    # curved or looping line (coastal paths, spits) can land off the line
    # entirely -- e.g. over water for a trail that hugs a bay. Interpolating
    # along the line itself guarantees a point that's actually on the trail.
    if geometry.geom_type == "MultiLineString":
        line = max(geometry.geoms, key=lambda piece: piece.length)
    else:
        line = geometry
    return line.interpolate(0.5, normalized=True)


def compute_trail_features(trail: pd.Series) -> dict:
    profiles = resample_trail(trail["geometry"])

    combined_profile = pd.concat(profiles, ignore_index=True)

    gain_grade = compute_gain_and_grade_stats(profiles)
    prominence = compute_prominence_features(combined_profile)
    tree_pct = compute_tree_cover_pct(combined_profile)

    midpoint = _representative_point(trail["geometry"])
    biome = find_biome(midpoint.y, midpoint.x)

    return {
        "osm_id": trail["osm_id"],
        "name": trail["name"],
        "distance_m": trail["distance_m"],
        **gain_grade,
        **prominence,
        "tree_cover_pct": tree_pct,
        **biome,
    }
