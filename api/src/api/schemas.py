from datetime import datetime

from pydantic import BaseModel


class TrailSummary(BaseModel):
    osm_id: int
    name: str
    distance_m: float
    is_loop: bool
    elevation_gain_m: float
    biome_name: str


class TrailDetail(TrailSummary):
    grade_std: float
    peak_elevation_m: float
    peak_prominence_m: float
    low_elevation_m: float
    low_relative_m: float
    tree_cover_pct: float
    eco_name: str
    realm: str


class TrailListResponse(BaseModel):
    total: int
    trails: list[TrailSummary]


class NearbyTrail(TrailSummary):
    distance_km: float


class TrailMapMarker(BaseModel):
    osm_id: int
    name: str
    distance_m: float
    start: list[float]


class TrailGeometry(BaseModel):
    osm_id: int
    lines: list[list[list[float]]]


class OfflineTileRef(BaseModel):
    z: int
    x: int
    y: int


class OfflineTileManifest(BaseModel):
    osm_id: int
    tiles: list[OfflineTileRef]


class RecommendationItem(BaseModel):
    osm_id: int
    name: str
    distance_m: float
    is_loop: bool
    elevation_gain_m: float
    biome_name: str
    similarity_score: float
    because_you_liked_osm_id: int


class EstimateTimeRequest(BaseModel):
    gpx: str


class EstimateTimeResponse(BaseModel):
    estimated_seconds: float
    range_low_seconds: float
    range_high_seconds: float
    distance_m: float


class AppleSignInRequest(BaseModel):
    identity_token: str


class SessionResponse(BaseModel):
    access_token: str


class LikeTrailRequest(BaseModel):
    osm_id: int


class HikeCreateRequest(BaseModel):
    distance_m: float
    moving_time_s: float
    osm_id: int | None = None


class HikeResponse(BaseModel):
    id: int
    distance_m: float
    moving_time_s: float
    completed_at: datetime
    osm_id: int | None
    trail_name: str | None
