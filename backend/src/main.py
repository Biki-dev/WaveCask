import logging
from contextlib import asynccontextmanager

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
from src.jobs import classify_tracks_nightly, sync_sessions_nightly

# Setup basic logging to stdout
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Configure database state and scheduled jobs during startup."""
    ensure_pgvector_extension()
    models.Base.metadata.create_all(bind=engine)
    ensure_vector_column()
    ensure_analytics_columns()

    scheduler.add_job(sync_sessions_nightly, CronTrigger(hour=2, minute=0), id="sync_sessions")
    scheduler.add_job(classify_tracks_nightly, CronTrigger(hour=2, minute=5), id="classify_tracks")
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

