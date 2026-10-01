const METERS_PER_MILE = 1609.344;
const METERS_PER_FOOT = 0.3048;

export function metersToMiles(m: number): number {
  return m / METERS_PER_MILE;
}

export function metersToFeet(m: number): number {
  return m / METERS_PER_FOOT;
}

export function formatElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${minutes}:${pad(seconds)}`;
}

// for describing an estimated duration (e.g. "3h 45m") -- distinct from
// formatElapsed's stopwatch-style "H:MM:SS", which reads oddly for an
// estimate ("3:45:00" looks like a clock time, not "about 3h45")
export function formatDuration(seconds: number): string {
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours === 0 ? `${minutes}m` : `${hours}h ${minutes}m`;
}

export function formatPace(elapsedMs: number, distanceM: number): string {
  const miles = metersToMiles(distanceM);
  if (miles < 0.05) return '--:--'; // not enough distance yet for a meaningful pace
  const minutesPerMile = elapsedMs / 1000 / 60 / miles;
  const wholeMinutes = Math.floor(minutesPerMile);
  const seconds = Math.round((minutesPerMile - wholeMinutes) * 60);
  return `${wholeMinutes}:${String(seconds).padStart(2, '0')} /mi`;
}
