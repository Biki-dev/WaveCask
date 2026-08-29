import os
import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

DEFAULT_DB = "postgresql://wavecask_user:wavecask_password@localhost:5432/wavecask_db"
if not os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL", "").startswith("postgresql://dummy"):
    os.environ["DATABASE_URL"] = DEFAULT_DB

from src import models
from src.database import engine, Base, ensure_pgvector_extension


@pytest.fixture(scope="function")
def db_session():
    """Yield a database session that rolls back all mutations after each test."""
    connection = engine.connect()

    try:
        ensure_pgvector_extension()
    except Exception:
        pass
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE raw_events ADD COLUMN IF NOT EXISTS delta_seconds NUMERIC(10,2) NOT NULL DEFAULT 0.0"))
            conn.execute(text("ALTER TABLE tracks ADD COLUMN IF NOT EXISTS total_watch_seconds NUMERIC(10,2) NOT NULL DEFAULT 0.0"))
            conn.execute(text("ALTER TABLE tracks ADD COLUMN IF NOT EXISTS preference DOUBLE PRECISION NOT NULL DEFAULT 0.5"))
            conn.execute(text("ALTER TABLE track_engagement ADD COLUMN IF NOT EXISTS preference DOUBLE PRECISION NOT NULL DEFAULT 0.5"))
    except Exception as err:
        print("DDL error:", err)

    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    try:
        Base.metadata.create_all(bind=connection)
    except Exception:
        pass

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
