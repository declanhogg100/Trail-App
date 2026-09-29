// Points at the local FastAPI server (see ../../api). Set to the Mac's LAN
// IP for physical-device testing (a real phone can't resolve "localhost" to
// your computer). Switch back to "http://localhost:8000" if testing on the
// iOS Simulator instead -- and re-run `ipconfig getifaddr en0` if this ever
// stops working, since your Mac's LAN IP can change between networks.
const API_BASE_URL = "http://192.168.4.33:8000";

// held in memory, attached to every authenticated request -- persisted
// separately to SecureStore by auth.ts, which restores it into here on launch
let sessionToken: string | null = null;

export function setSessionToken(token: string | null) {
  sessionToken = token;
}

export type TrailSummary = {
  osm_id: number;
  name: string;
  distance_m: number;
  elevation_gain_m: number;
  biome_name: string;
};

export type TrailDetail = TrailSummary & {
  grade_std: number;
  peak_elevation_m: number;
  peak_prominence_m: number;
  low_elevation_m: number;
  low_relative_m: number;
  tree_cover_pct: number;
  eco_name: string;
  realm: string;
};

export type TrailListResponse = {
  total: number;
  trails: TrailSummary[];
};

export type NearbyTrail = TrailSummary & {
  distance_km: number;
};

export type RecommendationItem = TrailSummary & {
  similarity_score: number;
  because_you_liked_osm_id: number;
};

export type TrailMapMarker = {
  osm_id: number;
  name: string;
  distance_m: number;
  start: [number, number];
};

export type TrailGeometry = {
  osm_id: number;
  // one coordinate array per disconnected piece of the trail -- most
  // trails have exactly one, but a merged trail with a gap in its
  // source data renders as multiple separate polylines
  lines: [number, number][][];
};

export type Hike = {
  id: number;
  distance_m: number;
  moving_time_s: number;
  completed_at: string;
  osm_id: number | null;
  trail_name: string | null;
};

export type EstimateTimeResponse = {
  estimated_seconds: number;
  range_low_seconds: number;
  range_high_seconds: number;
  distance_m: number;
};

// carries the HTTP status separately from the message, so callers can branch
// on specific status codes (e.g. treating /recommend's 400 as "no liked
// trails yet" rather than a generic failure) without parsing error text
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (sessionToken) headers["Authorization"] = `Bearer ${sessionToken}`;

  const response = await fetch(`${API_BASE_URL}${path}`, { headers, ...options });
  if (!response.ok) {
    const body = await response.text();
    throw new ApiError(response.status, `${response.status} ${response.statusText}: ${body}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

// --- auth ---

export async function signInWithApple(identityToken: string): Promise<string> {
  const { access_token } = await request<{ access_token: string }>("/auth/apple", {
    method: "POST",
    body: JSON.stringify({ identity_token: identityToken }),
  });
  setSessionToken(access_token);
  return access_token;
}

// only works if the backend has DEV_AUTH_ENABLED set -- returns a real,
// valid session token, just without going through Apple at all. Lets every
// other screen be built/tested in Expo Go while Sign in with Apple itself
// is blocked on a paid Apple Developer Program account.
export async function devSignIn(): Promise<string> {
  const { access_token } = await request<{ access_token: string }>("/auth/dev-bypass", {
    method: "POST",
  });
  setSessionToken(access_token);
  return access_token;
}

// --- trail catalog (public, no auth needed) ---

export function listTrails(
  params: { search?: string; limit?: number; offset?: number } = {}
): Promise<TrailListResponse> {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  const queryString = query.toString();
  return request(`/trails${queryString ? `?${queryString}` : ""}`);
}

export function getTrail(osmId: number): Promise<TrailDetail> {
  return request(`/trails/${osmId}`);
}

export function trailsNear(
  lat: number,
  lon: number,
  params: { radiusKm?: number; limit?: number } = {}
): Promise<NearbyTrail[]> {
  const query = new URLSearchParams({ lat: String(lat), lon: String(lon) });
  if (params.radiusKm !== undefined) query.set("radius_km", String(params.radiusKm));
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  return request(`/trails/near?${query.toString()}`);
}

export function trailsInBounds(bounds: {
  minLon: number;
  minLat: number;
  maxLon: number;
  maxLat: number;
}): Promise<TrailMapMarker[]> {
  const query = new URLSearchParams({
    min_lon: String(bounds.minLon),
    min_lat: String(bounds.minLat),
    max_lon: String(bounds.maxLon),
    max_lat: String(bounds.maxLat),
  });
  return request(`/trails/map?${query.toString()}`);
}

export function getTrailGeometry(osmId: number): Promise<TrailGeometry> {
  return request(`/trails/${osmId}/geometry`);
}

// --- liked trails (requires sign-in) ---

export function listLikedTrails(): Promise<TrailSummary[]> {
  return request("/me/liked-trails");
}

export function likeTrail(osmId: number): Promise<void> {
  return request("/me/liked-trails", {
    method: "POST",
    body: JSON.stringify({ osm_id: osmId }),
  });
}

export function unlikeTrail(osmId: number): Promise<void> {
  return request(`/me/liked-trails/${osmId}`, { method: "DELETE" });
}

// --- hike history (requires sign-in) ---

export function listHikes(): Promise<Hike[]> {
  return request("/me/hikes");
}

export function logHike(distanceM: number, movingTimeS: number, osmId?: number): Promise<Hike> {
  return request("/me/hikes", {
    method: "POST",
    body: JSON.stringify({ distance_m: distanceM, moving_time_s: movingTimeS, osm_id: osmId ?? null }),
  });
}

// --- model-backed endpoints (require sign-in; read liked trails / hike
// history server-side rather than taking them as request parameters) ---

export function getRecommendations(topK = 10): Promise<RecommendationItem[]> {
  return request(`/recommend?top_k=${topK}`, { method: "POST" });
}

export function estimateTime(gpx: string): Promise<EstimateTimeResponse> {
  return request("/estimate-time", {
    method: "POST",
    body: JSON.stringify({ gpx }),
  });
}
