import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from time_estimator.pipeline.parse_gpx import (
    compute_grade,
    load_gpx_points,
    resample_by_distance,
)

df = load_gpx_points("data/raw/Mojstrovka.gpx")

print(df.head())
print("---")
print(f"num points: {len(df)}")
print(f"total distance: {df['cumulative_distance_m'].iloc[-1]:.1f} m")
print(f"elevation range: {df['elevation'].min():.1f} - {df['elevation'].max():.1f} m")

resampled = resample_by_distance(df, step_m=40.0)
resampled = compute_grade(resampled)
print("---")
print(resampled)
print(f"num segments: {len(resampled)}")
print(f"grade range: {resampled['grade'].min():.3f} - {resampled['grade'].max():.3f}")

fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(6, 7))
ax1.plot(df["cumulative_distance_m"], df["elevation"], label="raw points", alpha=0.5)
ax1.plot(resampled["distance_m"], resampled["elevation"], "o-", label="resampled (40m)", markersize=3)
ax1.set_ylabel("elevation (m)")
ax1.set_title("Mojstrovka: elevation and grade")
ax1.legend()

ax2.plot(resampled["distance_m"], resampled["grade"], "o-", color="tab:red", markersize=3)
ax2.axhline(0, color="black", linewidth=0.5)
ax2.set_xlabel("cumulative distance (m)")
ax2.set_ylabel("grade (rise/run)")

fig.savefig("data/mojstrovka_profile.png")
