from contextlib import asynccontextmanager
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, HTTPException
from recommender.inference import TrailRecommender
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
from api.schemas import (
    AppleSignInRequest,
    EstimateTimeRequest,
    EstimateTimeResponse,
    HikeCreateRequest,
    HikeResponse,
    LikeTrailRequest,
    NearbyTrail,
    RecommendationItem,
    SessionResponse,
    TrailDetail,
    TrailListResponse,
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
    models["time_estimator"] = TimeEstimator(
        model_path=_TIME_ESTIMATOR_DATA / "gru_time_estimator.pt",
        stats_path=_TIME_ESTIMATOR_DATA / "inference_stats.pkl",
    )
    yield
    models.clear()


app = FastAPI(title="Trail App API", lifespan=lifespan)


@app.get("/trails", response_model=TrailListResponse)
def list_trails(search: str | None = None, limit: int = 50, offset: int = 0):
    return models["recommender"].list_trails(search=search, limit=limit, offset=offset)


@app.get("/trails/near", response_model=list[NearbyTrail])
def trails_near(lat: float, lon: float, radius_km: float = 50.0, limit: int = 20):
    return models["recommender"].near(lat, lon, radius_km=radius_km, limit=limit)


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


@app.post("/recommend", response_model=list[RecommendationItem])
def recommend(
    top_k: int = 10, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    liked_osm_ids = [row.osm_id for row in db.query(LikedTrail).filter(LikedTrail.user_id == user.id)]
    try:
        return models["recommender"].recommend(liked_osm_ids, top_k=top_k)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/estimate-time", response_model=EstimateTimeResponse)
def estimate_time(
    request: EstimateTimeRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    previous_hikes = [
        {"distance_m": h.distance_m, "moving_time_s": h.moving_time_s}
        for h in db.query(Hike).filter(Hike.user_id == user.id)
    ]
    try:
        return models["time_estimator"].predict(request.gpx, previous_hikes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"failed to parse or estimate hike: {e}")
