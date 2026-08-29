import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from sqlalchemy import text

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src import models
from src.api.routes.events import router as events_router
from src.api.routes.playlists import router as playlists_router
from src.api.routes.sessions import router as sessions_router
from src.api.routes.system import router as system_router
from src.api.routes.tracks import router as tracks_router
from src.database import (
    ensure_analytics_columns,
    ensure_pgvector_extension,
    ensure_vector_column,
    engine,
)
from src.jobs import classify_tracks_nightly, sync_sessions_nightly, recommendation_models_nightly

# Setup basic logging to stdout
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

scheduler = BackgroundScheduler()

_SQL_MIGRATION = Path(__file__).parent.parent / "sql" / "001_recommendation_engine.sql"


def _apply_recommendation_migration() -> None:
    """Run the idempotent recommendation-engine SQL migration at startup."""
    if not _SQL_MIGRATION.exists():
        logging.getLogger(__name__).warning(
            "Recommendation migration not found: %s", _SQL_MIGRATION
        )
        return
    sql = _SQL_MIGRATION.read_text()
    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
    logging.getLogger(__name__).info(
        "Recommendation migration applied: %s", _SQL_MIGRATION.name
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Configure database state and scheduled jobs during startup."""
    ensure_pgvector_extension()
    models.Base.metadata.create_all(bind=engine)
    ensure_vector_column()
    ensure_analytics_columns()
    _apply_recommendation_migration()

    scheduler.add_job(sync_sessions_nightly, CronTrigger(hour=2, minute=0), id="sync_sessions")
    scheduler.add_job(classify_tracks_nightly, CronTrigger(hour=2, minute=5), id="classify_tracks")
    scheduler.add_job(
        recommendation_models_nightly,
        CronTrigger(hour=4, minute=0),
        id="recommendation_models",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()

    yield

    scheduler.shutdown()


app = FastAPI(
    title="WaveCask API",
    description="WaveCask description",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events_router)
app.include_router(sessions_router)
app.include_router(tracks_router)
app.include_router(playlists_router)
app.include_router(system_router)

