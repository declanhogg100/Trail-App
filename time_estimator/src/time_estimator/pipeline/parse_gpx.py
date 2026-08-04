from pathlib import Path

import gpxpy
import numpy as np
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


def resample_by_distance(df: pd.DataFrame, step_m: float = 40.0) -> pd.DataFrame:
    total_distance = df["cumulative_distance_m"].iloc[-1]
    distance_marks = np.arange(0, total_distance, step_m)

    elevation = np.interp(distance_marks, df["cumulative_distance_m"], df["elevation"])
    lat = np.interp(distance_marks, df["cumulative_distance_m"], df["lat"])
    lon = np.interp(distance_marks, df["cumulative_distance_m"], df["lon"])

    return pd.DataFrame(
        {
            "distance_m": distance_marks,
            "lat": lat,
            "lon": lon,
            "elevation": elevation,
        }
    )


def compute_grade(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    rise = df["elevation"].diff()
    hypotenuse = df["distance_m"].diff()
    # distance_m is 3D (path) distance, i.e. the hypotenuse of rise and horizontal
    # run -- grade is conventionally rise/run, so back out the horizontal leg first.
    run = np.sqrt(np.maximum(hypotenuse**2 - rise**2, 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        grade = rise / run
    df["grade"] = grade.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return df
