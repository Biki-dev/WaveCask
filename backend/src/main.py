from fastapi import FastAPI, Depends, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src import models, schemas
from src.database import engine, get_db
from src.jobs import sync_sessions_nightly

scheduler = BackgroundScheduler()

# Lifespan context manager for startup and shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup - Create tables in the database if they don't exist
    models.Base.metadata.create_all(bind=engine)
    
    # Runs at 2:00 AM every night
    scheduler.add_job(
        sync_sessions_nightly, 
        CronTrigger(hour=2, minute=0)
    )
    scheduler.start()
    
    yield
    
    # Teardown
    scheduler.shutdown()

app = FastAPI(
    title="WaveCask API",
    description="WaveCask description",
    version="0.1.0",
    lifespan=lifespan
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
    # Create the database model instance from the pydantic model
    db_event = models.RawEvent(**event.model_dump())

    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    
    return db_event

# all Session
@app.get("/api/sessions", response_model=list[schemas.SessionSummaryResponse])
def list_sessions(db: Session = Depends(get_db)):
    return db.query(models.SessionSummary).all()

# Get a specific session by session_id
@app.get("/api/sessions/{session_id}", response_model=schemas.SessionSummaryResponse)
def get_session(session_id: str, db: Session = Depends(get_db)):
    session = db.query(models.SessionSummary).filter(models.SessionSummary.session_id == session_id).first()
    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Session not found")
    return session

# Trigger the nightly sync job manually
@app.post("/api/sessions/sync", status_code=status.HTTP_202_ACCEPTED)
def trigger_sync(background_tasks: BackgroundTasks):
    background_tasks.add_task(sync_sessions_nightly)
    return {"message": "Session sync job started"}

@app.get("/health")
def health_check():
    return {"status": "ok"}
