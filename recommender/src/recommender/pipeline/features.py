import pandas as pd

from recommender.pipeline.biome import find_biome
from recommender.pipeline.elevation import (
    compute_gain_and_grade_stats,
    compute_prominence_features,
    resample_trail,
)
from recommender.pipeline.landcover import compute_tree_cover_pct
from recommender.pipeline.osm_trails import _GEOD

# a trailhead loop rarely closes to the exact same point (parking lot
# geometry, GPS snapping) -- treat anything that comes back within this
# distance of its own start as a loop; anything farther apart is dictated to
# be an out-and-back (there's no "point to point with a shuttle" case in
# this catalog, so that's the only other option)
LOOP_CLOSURE_THRESHOLD_M = 100.0


def _is_loop(geometry) -> bool:
    # a MultiLineString's pieces aren't guaranteed connected/ordered (a gap
    # in the source data) -- "start" and "end" are still just the first
    # point of the first piece and the last point of the last piece, same
    # convention the frontend already uses for a trail's start marker
    if geometry.geom_type == "MultiLineString":
        pieces = list(geometry.geoms)
        start, end = pieces[0].coords[0], pieces[-1].coords[-1]
    else:
        start, end = geometry.coords[0], geometry.coords[-1]
    _, _, closure_distance_m = _GEOD.inv(start[0], start[1], end[0], end[1])
    return closure_distance_m <= LOOP_CLOSURE_THRESHOLD_M


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
        "is_loop": _is_loop(trail["geometry"]),
        **gain_grade,
        **prominence,
        "tree_cover_pct": tree_pct,
        **biome,
        # stored for location-based search (e.g. "near Big Sur"), not fed
        # into the similarity model -- two trails being geographically close
        # says nothing about whether they're similar in character
        "lat": midpoint.y,
        "lon": midpoint.x,
    }
