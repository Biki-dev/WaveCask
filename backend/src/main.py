from fastapi import FastAPI, Depends, status, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src import models, schemas
from src.database import engine, get_db
from src.jobs import sync_sessions_nightly, classify_tracks_nightly
from src.tracks_service import upsert_track_from_event

scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create all tables (raw_events, sessions, tracks)
    models.Base.metadata.create_all(bind=engine)

    # Nightly jobs — both run at 2:00 AM
    scheduler.add_job(sync_sessions_nightly, CronTrigger(hour=2, minute=0), id="sync_sessions")
    scheduler.add_job(classify_tracks_nightly, CronTrigger(hour=2, minute=5), id="classify_tracks")
    scheduler.start()
    
    yield
    
    # Teardown
    scheduler.shutdown()

app = FastAPI(
    title="WaveCask API",
    description="WaveCask description",
    version="0.1.0",
    lifespan=lifespan,
)

# Allow CORS for the extension to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/rawevents", response_model=schemas.RawEventResponse, status_code=status.HTTP_201_CREATED)
def create_event(event: schemas.RawEventCreate, db: Session = Depends(get_db)):
    """Save a raw event and immediately upsert a track stub if video_id is present."""
    db_event = models.RawEvent(**event.model_dump())

    db.add(db_event)
    db.commit()
    db.refresh(db_event)

    # Step 1 of the pipeline: create/update the track stub in the tracks table
    upsert_track_from_event(db, db_event)

    return db_event

# all Session
@app.get("/api/sessions", response_model=list[schemas.SessionSummaryResponse])
def list_sessions(db: Session = Depends(get_db)):
    return db.query(models.SessionSummary).all()

# Get a specific session by session_id
@app.get("/api/sessions/{session_id}", response_model=schemas.SessionSummaryResponse)
def get_session(session_id: str, db: Session = Depends(get_db)):
    session = (
        db.query(models.SessionSummary)
        .filter(models.SessionSummary.session_id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session

# Trigger the nightly sync job manually
@app.post("/api/sessions/sync", status_code=status.HTTP_202_ACCEPTED)
def trigger_session_sync(background_tasks: BackgroundTasks):
    background_tasks.add_task(sync_sessions_nightly)
    return {"message": "Session sync job started"}

@app.get("/api/tracks", response_model=list[schemas.TrackResponse])
def list_tracks(
    status_filter: str | None = None,
    db: Session = Depends(get_db),
):
    """List all tracks. Optionally filter by processing_status."""
    q = db.query(models.Track)
    if status_filter:
        q = q.filter(models.Track.processing_status == status_filter)
    return q.all()


@app.get("/api/tracks/{video_id}", response_model=schemas.TrackResponse)
def get_track(video_id: str, db: Session = Depends(get_db)):
    track = db.query(models.Track).filter(models.Track.video_id == video_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    return track


@app.post("/api/tracks/classify", status_code=status.HTTP_202_ACCEPTED)
def trigger_classification(background_tasks: BackgroundTasks):
    """Manually trigger the 3-layer classification pipeline on all pending tracks."""
    background_tasks.add_task(classify_tracks_nightly)
    return {"message": "Track classification started"}

@app.get("/health")
def health_check():
    return {"status": "ok"}
