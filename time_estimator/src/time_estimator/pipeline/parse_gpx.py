from pathlib import Path

import gpxpy
import pandas as pd


def load_gpx_points(filepath: str | Path) -> pd.DataFrame:
    with open(filepath, "r") as f:
        gpx = gpxpy.parse(f)

    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                points.append(point)

    rows = [
        {
            "lat": point.latitude,
            "lon": point.longitude,
            "elevation": point.elevation,
            "time": point.time,
        }
        for point in points
    ]
    df = pd.DataFrame(rows)

    cumulative_distance_m = [0.0]
    for i in range(1, len(points)):
        step = points[i - 1].distance_3d(points[i])
        cumulative_distance_m.append(cumulative_distance_m[-1] + step)

    df["cumulative_distance_m"] = cumulative_distance_m
    return df
