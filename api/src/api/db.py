from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "trailapp.db"
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
