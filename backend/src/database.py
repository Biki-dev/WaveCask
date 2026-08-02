import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Ensure the pgvector extension is installed in the database
def ensure_pgvector_extension() -> None:
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

# Ensure the audio_embedding column is of type vector(512)
def ensure_vector_column() -> None:
    check_sql = text("""
        SELECT data_type
          FROM information_schema.columns
         WHERE table_name  = 'tracks'
           AND column_name = 'audio_embedding'
    """)
    with engine.connect() as conn:
        row = conn.execute(check_sql).fetchone()
        if row and row[0].lower() == "text":
            conn.execute(text(
                "ALTER TABLE tracks "
                "ALTER COLUMN audio_embedding TYPE vector(512) "
                "USING audio_embedding::vector"
            ))
            conn.commit()


def ensure_analytics_columns() -> None:
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE raw_events ADD COLUMN IF NOT EXISTS delta_seconds NUMERIC(10,2) NOT NULL DEFAULT 0.0"
        ))
        conn.execute(text(
            "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS total_watch_seconds NUMERIC(10,2) NOT NULL DEFAULT 0.0"
        ))
        conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


