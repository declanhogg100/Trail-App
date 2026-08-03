import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from time_estimator.pipeline.parse_gpx import load_gpx_points

df = load_gpx_points("data/raw/Mojstrovka.gpx")

print(df.head())
print("---")
print(f"num points: {len(df)}")
print(f"total distance: {df['cumulative_distance_m'].iloc[-1]:.1f} m")
print(f"elevation range: {df['elevation'].min():.1f} - {df['elevation'].max():.1f} m")

fig, ax = plt.subplots()
ax.plot(df["cumulative_distance_m"], df["elevation"])
ax.set_xlabel("cumulative distance (m)")
ax.set_ylabel("elevation (m)")
ax.set_title("Mojstrovka elevation profile")
fig.savefig("data/mojstrovka_profile.png")
