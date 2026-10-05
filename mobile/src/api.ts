// Set via EXPO_PUBLIC_API_BASE_URL (see mobile/.env for the local-dev
// default, mobile/.env.local for a personal override, and eas.json for a
// production build's URL -- see Expo's env var docs). Falls back to
// localhost if somehow unset. For local-device testing over LAN, .env's
// value needs your Mac's current LAN IP -- re-run `ipconfig getifaddr en0`
// if that ever stops working, since it can change between networks.
const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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
  is_loop: boolean;
  elevation_gain_m: number;
  elevation_loss_m: number;
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

// invalidates the current session token server-side (not just locally) --
// a stolen token stops working immediately on sign-out, rather than
// remaining valid until its 30-day expiry just because nobody has it anymore
export function signOutOnServer(): Promise<void> {
  return request("/auth/sign-out", { method: "POST" });
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

export type OfflineTileRef = { z: number; x: number; y: number };
export type OfflineTileManifest = { osm_id: number; tiles: OfflineTileRef[] };

export function getOfflineTileManifest(osmId: number): Promise<OfflineTileManifest> {
  return request(`/trails/${osmId}/offline-tiles`);
}

// used with File.downloadFileAsync, not the request() helper -- that's a
// direct binary download, not a JSON API call
export function offlineTileUrl(osmId: number, tile: OfflineTileRef): string {
  return `${API_BASE_URL}/trails/${osmId}/offline-tiles/${tile.z}/${tile.x}/${tile.y}.png`;
}

// a {z}/{x}/{y} URL template (not a single tile URL) -- handed straight to
// MapLibre's RasterSource so it can fetch tiles live, one at a time, while
// you have signal. The same backend endpoint also renders+caches on first
// request, so this works even for a trail that was never bulk-downloaded.
export function offlineTileUrlTemplate(osmId: number): string {
  return `${API_BASE_URL}/trails/${osmId}/offline-tiles/{z}/{x}/{y}.png`;
}

// permanently deletes the account and all of its data (liked trails, hike
// history) server-side -- required by App Store review guideline 5.1.1(v)
export function deleteAccount(): Promise<void> {
  return request('/me', { method: 'DELETE' });
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

export function deleteHike(id: number): Promise<void> {
  return request(`/me/hikes/${id}`, { method: "DELETE" });
}

// --- model-backed endpoints (require sign-in; read liked trails / hike
// history server-side rather than taking them as request parameters) ---

export function getRecommendations(topK = 10): Promise<RecommendationItem[]> {
  return request(`/recommend?top_k=${topK}`, { method: "POST" });
}

// roundTrip left undefined defers to the trail's own is_loop guess
// server-side; pass it explicitly to override that guess (see
// TrailDetailContent's out-and-back toggle)
export function estimateTrailTime(osmId: number, roundTrip?: boolean): Promise<EstimateTimeResponse> {
  const query = roundTrip === undefined ? '' : `?round_trip=${roundTrip}`;
  return request(`/trails/${osmId}/estimate-time${query}`);
}
