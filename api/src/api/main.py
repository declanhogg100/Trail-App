from contextlib import asynccontextmanager
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from recommender.geometry_store import TrailGeometryStore
from recommender.inference import TrailRecommender
from recommender.offline_tile_store import OfflineTileStore
from recommender.profile_store import TrailProfileStore
from sqlalchemy.orm import Session
from time_estimator.inference import TimeEstimator

from api.auth import (
    DEV_AUTH_ENABLED,
    DEV_AUTH_SUB,
    create_session_token,
    get_current_user,
    get_or_create_user,
    verify_apple_identity_token,
)
from api.db import Base, engine, get_db
from api.models import Hike, LikedTrail, User
from api.privacy_policy import PRIVACY_POLICY_HTML
from api.schemas import (
    AppleSignInRequest,
    EstimateTimeRequest,
    EstimateTimeResponse,
    HikeCreateRequest,
    HikeResponse,
    LikeTrailRequest,
    NearbyTrail,
    OfflineTileManifest,
    RecommendationItem,
    SessionResponse,
    TrailDetail,
    TrailGeometry,
    TrailListResponse,
    TrailMapMarker,
    TrailSummary,
)

# recommender/inference.py and time_estimator/inference.py each locate their
# OWN data/ folder relative to their own __file__ by default -- that only
# works when running from their original source checkout. Once installed as
# a dependency into this project's venv, __file__ resolves inside
# api/.venv/site-packages instead, which has no relation to the sibling
# projects' data/ directories. This is the one place that actually needs to
# know the multi-project repo layout, so paths are passed explicitly here.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_RECOMMENDER_DATA = _REPO_ROOT / "recommender" / "data"
_TIME_ESTIMATOR_DATA = _REPO_ROOT / "time_estimator" / "data" / "hikr"

models: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)

    # loaded once at process startup, not per-request -- the recommender in
    # particular precomputes an embedding for the entire trail catalog, which
    # would be wasteful to redo on every call
    models["recommender"] = TrailRecommender(
        features_path=_RECOMMENDER_DATA / "trail_features.parquet",
        model_path=_RECOMMENDER_DATA / "trail_encoder.pt",
        stats_path=_RECOMMENDER_DATA / "feature_stats.pkl",
    )
    models["geometry_store"] = TrailGeometryStore(
        geometries_path=_RECOMMENDER_DATA / "trail_geometries.parquet",
    )
    models["profile_store"] = TrailProfileStore(
        profiles_path=_RECOMMENDER_DATA / "trail_elevation_profiles.parquet",
    )
    models["offline_tile_store"] = OfflineTileStore()
    models["time_estimator"] = TimeEstimator(
        model_path=_TIME_ESTIMATOR_DATA / "gru_time_estimator.pt",
        stats_path=_TIME_ESTIMATOR_DATA / "inference_stats.pkl",
    )
    yield
    models.clear()


app = FastAPI(title="Trail App API", lifespan=lifespan)


# public, no auth -- this is the URL App Store Connect's privacy policy
# field points to, so it needs to be reachable by anyone, not just signed-in
# app users
@app.get("/privacy", response_class=HTMLResponse)
def privacy_policy():
    return PRIVACY_POLICY_HTML


@app.get("/trails", response_model=TrailListResponse)
def list_trails(search: str | None = None, limit: int = 50, offset: int = 0):
    return models["recommender"].list_trails(search=search, limit=limit, offset=offset)


@app.get("/trails/near", response_model=list[NearbyTrail])
def trails_near(lat: float, lon: float, radius_km: float = 50.0, limit: int = 20):
    return models["recommender"].near(lat, lon, radius_km=radius_km, limit=limit)


@app.get("/trails/map", response_model=list[TrailMapMarker])
def trails_map(min_lon: float, min_lat: float, max_lon: float, max_lat: float):
    return models["geometry_store"].markers_in_bbox(min_lon, min_lat, max_lon, max_lat)


@app.get("/trails/{osm_id}/geometry", response_model=TrailGeometry)
def get_trail_geometry(osm_id: int):
    lines = models["geometry_store"].get_lines(osm_id)
    if lines is None:
        raise HTTPException(status_code=404, detail=f"no trail geometry for osm_id {osm_id}")
    return {"osm_id": osm_id, "lines": lines}


@app.get("/trails/{osm_id}/offline-tiles", response_model=OfflineTileManifest)
def get_offline_tile_manifest(osm_id: int):
    lines = models["geometry_store"].get_lines(osm_id)
    if lines is None:
        raise HTTPException(status_code=404, detail=f"no trail geometry for osm_id {osm_id}")
    # renders and disk-caches on first request for this trail (a few
    # seconds), just returns the cached list on every request after
    tiles = models["offline_tile_store"].get_manifest(osm_id, lines)
    return {"osm_id": osm_id, "tiles": tiles}


@app.get("/trails/{osm_id}/offline-tiles/{z}/{x}/{y}.png")
def get_offline_tile(osm_id: int, z: int, x: int, y: int):
    lines = models["geometry_store"].get_lines(osm_id)
    if lines is None:
        raise HTTPException(status_code=404, detail=f"no trail geometry for osm_id {osm_id}")
    # renders+caches this trail's tiles on first request if they aren't
    # already -- lets the map use this endpoint as a live source (fetching
    # tiles one at a time while you have signal) for a trail that was never
    # bulk-downloaded ahead of time, not just for the download flow
    tile_bytes = models["offline_tile_store"].get_tile_bytes(osm_id, z, x, y, lines)
    if tile_bytes is None:
        raise HTTPException(status_code=404, detail="no tile at this z/x/y for this trail")
    return Response(content=tile_bytes, media_type="image/png")


@app.get("/trails/{osm_id}", response_model=TrailDetail)
def get_trail(osm_id: int):
    trail = models["recommender"].get_trail(osm_id)
    if trail is None:
        raise HTTPException(status_code=404, detail=f"no trail with osm_id {osm_id}")
    return trail


@app.post("/auth/apple", response_model=SessionResponse)
def sign_in_with_apple(request: AppleSignInRequest, db: Session = Depends(get_db)):
    try:
        apple_sub = verify_apple_identity_token(request.identity_token)
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"invalid Apple identity token: {e}")

    user = get_or_create_user(db, apple_sub)
    return {"access_token": create_session_token(user.id)}


@app.post("/auth/dev-bypass", response_model=SessionResponse)
def dev_sign_in(db: Session = Depends(get_db)):
    # skips real Apple verification entirely -- only reachable when
    # DEV_AUTH_ENABLED is explicitly set, so this can't accidentally work
    # anywhere this server is actually deployed
    if not DEV_AUTH_ENABLED:
        raise HTTPException(status_code=404)

    user = get_or_create_user(db, DEV_AUTH_SUB)
    return {"access_token": create_session_token(user.id)}


@app.delete("/me", status_code=204)
def delete_account(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # cascade="all, delete-orphan" on User.liked_trails and User.hikes (see
    # models.py) takes care of removing those rows too -- required by App
    # Store review guideline 5.1.1(v): any app offering account creation
    # must offer in-app account deletion, not just a website/support request
    db.delete(user)
    db.commit()


@app.get("/me/liked-trails", response_model=list[TrailSummary])
def list_liked_trails(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    liked = db.query(LikedTrail).filter(LikedTrail.user_id == user.id).all()
    trails = [models["recommender"].get_trail(row.osm_id) for row in liked]
    return [t for t in trails if t is not None]


@app.post("/me/liked-trails", status_code=204)
def like_trail(
    request: LikeTrailRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if models["recommender"].get_trail(request.osm_id) is None:
        raise HTTPException(status_code=404, detail=f"no trail with osm_id {request.osm_id}")

    already_liked = (
        db.query(LikedTrail)
        .filter(LikedTrail.user_id == user.id, LikedTrail.osm_id == request.osm_id)
        .one_or_none()
    )
    if already_liked is None:
        db.add(LikedTrail(user_id=user.id, osm_id=request.osm_id))
        db.commit()


@app.delete("/me/liked-trails/{osm_id}", status_code=204)
def unlike_trail(osm_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(LikedTrail).filter(LikedTrail.user_id == user.id, LikedTrail.osm_id == osm_id).delete()
    db.commit()


def _to_hike_response(hike: Hike) -> dict:
    trail_name = None
    if hike.osm_id is not None:
        trail = models["recommender"].get_trail(hike.osm_id)
        trail_name = trail["name"] if trail is not None else None
    return {
        "id": hike.id,
        "distance_m": hike.distance_m,
        "moving_time_s": hike.moving_time_s,
        "completed_at": hike.completed_at,
        "osm_id": hike.osm_id,
        "trail_name": trail_name,
    }


@app.get("/me/hikes", response_model=list[HikeResponse])
def list_hikes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    hikes = db.query(Hike).filter(Hike.user_id == user.id).order_by(Hike.completed_at.desc()).all()
    return [_to_hike_response(h) for h in hikes]


@app.post("/me/hikes", response_model=HikeResponse)
def log_hike(
    request: HikeCreateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    hike = Hike(
        user_id=user.id,
        distance_m=request.distance_m,
        moving_time_s=request.moving_time_s,
        osm_id=request.osm_id,
    )
    db.add(hike)
    db.commit()
    db.refresh(hike)
    return _to_hike_response(hike)


@app.delete("/me/hikes/{hike_id}", status_code=204)
def delete_hike(hike_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # scoped to the current user, not just a bare ID lookup -- otherwise one
    # user could delete another's hike just by guessing/incrementing an id
    db.query(Hike).filter(Hike.id == hike_id, Hike.user_id == user.id).delete()
    db.commit()


@app.post("/recommend", response_model=list[RecommendationItem])
def recommend(
    top_k: int = 10, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    liked_osm_ids = [row.osm_id for row in db.query(LikedTrail).filter(LikedTrail.user_id == user.id)]
    try:
        return models["recommender"].recommend(liked_osm_ids, top_k=top_k)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _previous_hikes(user: User, db: Session) -> list[dict]:
    return [
        {"distance_m": h.distance_m, "moving_time_s": h.moving_time_s}
        for h in db.query(Hike).filter(Hike.user_id == user.id)
    ]


@app.post("/estimate-time", response_model=EstimateTimeResponse)
def estimate_time(
    request: EstimateTimeRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    try:
        return models["time_estimator"].predict(request.gpx, _previous_hikes(user, db))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"failed to parse or estimate hike: {e}")


@app.get("/trails/{osm_id}/estimate-time", response_model=EstimateTimeResponse)
def estimate_trail_time(
    osm_id: int,
    round_trip: bool | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = models["profile_store"].get_profile(osm_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"no elevation profile for osm_id {osm_id}")

    # is_loop can't distinguish a genuine out-and-back from a point-to-point
    # trail that just happens to start and end in different places (e.g.
    # Trans-Catalina Trail, hiked once between two different harbors) --
    # both look identical as a line. round_trip lets the person who
    # actually knows their own plans override the guess explicitly, rather
    # than trying to infer it from geometry alone.
    trail = models["recommender"].get_trail(osm_id)
    should_round_trip = round_trip if round_trip is not None else (trail is not None and not trail["is_loop"])

    estimate = models["time_estimator"].predict_from_profile(profile, _previous_hikes(user, db))

    if should_round_trip:
        # the GRU is trained only on single-day hikr.org hikes capped at
        # 80km / 16h (see DISTANCE_RANGE_M in hikr_dataset.py) -- feeding it
        # a doubled-length round-trip profile pushes well past anything it
        # saw in training and its output saturates instead of scaling, so a
        # 122km round trip predicts almost the same time as the 61km one-way
        # version. Doubling the model's own (in-distribution) one-way
        # estimate is a far safer assumption than trusting that extrapolation.
        estimate = {
            "estimated_seconds": estimate["estimated_seconds"] * 2,
            "range_low_seconds": estimate["range_low_seconds"] * 2,
            "range_high_seconds": estimate["range_high_seconds"] * 2,
            "distance_m": estimate["distance_m"] * 2,
        }

    return estimate
