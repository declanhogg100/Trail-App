from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Apple's stable, unique identifier for this user -- what we actually
    # authenticate against, never their email/name (which Apple only sends
    # on the very first sign-in and may withhold thereafter)
    apple_sub: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    # bumped to "now" on sign-out -- any session token issued before this
    # point is rejected even though its signature and expiry are still
    # valid, since a JWT alone has no way to be individually revoked. NULL
    # means no sign-out has ever invalidated anything yet.
    tokens_invalid_before: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    liked_trails: Mapped[list["LikedTrail"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    hikes: Mapped[list["Hike"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class LikedTrail(Base):
    __tablename__ = "liked_trails"
    __table_args__ = (UniqueConstraint("user_id", "osm_id", name="uq_user_trail"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # references a trail in the recommender's catalog (trail_features.parquet)
    # -- not a DB foreign key, since that catalog lives outside this database
    osm_id: Mapped[int] = mapped_column(Integer, nullable=False)
    liked_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    user: Mapped["User"] = relationship(back_populates="liked_trails")


class Hike(Base):
    __tablename__ = "hikes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    moving_time_s: Mapped[float] = mapped_column(Float, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    # which trail this was, if any -- nullable so a hike logged some other
    # way (not through Active Hike) doesn't require one. Not a DB foreign
    # key, same reasoning as LikedTrail.osm_id: the catalog lives outside
    # this database.
    osm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped["User"] = relationship(back_populates="hikes")
