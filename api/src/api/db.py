import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# defaults to living alongside the source (fine for local dev); in
# production this should point at a path on a persistent, mounted volume --
# otherwise user accounts/hikes/likes vanish on every redeploy
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "trailapp.db"
_DB_PATH = Path(os.environ.get("DATABASE_PATH", _DEFAULT_DB_PATH))
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{_DB_PATH}")
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
