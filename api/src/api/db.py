import os
from pathlib import Path

from sqlalchemy import create_engine, text
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


def run_migrations() -> None:
    """Base.metadata.create_all() only creates missing TABLES, never adds
    columns to one that already exists -- there's no Alembic (or similar)
    in this small a project, so new columns get a one-off ALTER TABLE here
    instead. Checked via PRAGMA first (rather than try/except around the
    ALTER itself) since a failed statement mid-transaction can otherwise
    leave the connection unable to cleanly commit."""
    with engine.begin() as conn:
        existing_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        if "tokens_invalid_before" not in existing_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN tokens_invalid_before DATETIME"))
