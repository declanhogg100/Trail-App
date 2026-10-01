import * as Location from 'expo-location';

// Turns a place name ("Big Sur") into coordinates using the device's own
// geocoding (Apple's on iOS). Runs entirely client-side -- our backend never
// sees the place name, only the resulting lat/lon once this resolves.
export async function geocodeArea(query: string): Promise<{ lat: number; lon: number } | null> {
  const { status } = await Location.requestForegroundPermissionsAsync();
  if (status !== 'granted') {
    throw new Error('Location permission is required to search by area');
  }

  const results = await Location.geocodeAsync(query);
  if (results.length === 0) {
    return null;
  }

  // geocodeAsync can return multiple matches for an ambiguous query -- take
  // the first (highest-confidence) one rather than asking the user to choose
  const { latitude, longitude } = results[0];
  return { lat: latitude, lon: longitude };
}

// the device's own current GPS position -- distinct from geocodeArea, which
// resolves a typed place name instead of where the user actually is right now
export async function getCurrentLocation(): Promise<{ lat: number; lon: number }> {
  const { status } = await Location.requestForegroundPermissionsAsync();
  if (status !== 'granted') {
    throw new Error('Location permission is required to find hikes near you');
  }

  try {
    const position = await Location.getCurrentPositionAsync({
      accuracy: Location.Accuracy.Balanced,
    });
    return { lat: position.coords.latitude, lon: position.coords.longitude };
  } catch {
    // getCurrentPositionAsync throws a raw native CoreLocation/FusedLocation
    // exception on failure (e.g. kCLErrorDomain error 0, "location unknown")
    // -- happens on a real device with no GPS fix (indoors, etc.), and
    // reliably on the iOS Simulator whenever no location is configured.
    // Normalize to one clean, user-facing message either way.
    throw new Error("Couldn't determine your current location. Make sure location services are enabled.");
  }
}
