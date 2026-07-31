from fastapi import FastAPI, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager

from src import models, schemas
from src.database import engine, get_db

# Lifespan context manager for startup and shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup - Create tables in the database if they don't exist
    models.Base.metadata.create_all(bind=engine)
    yield

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

@app.get("/health")
def health_check():
    return {"status": "ok"}
