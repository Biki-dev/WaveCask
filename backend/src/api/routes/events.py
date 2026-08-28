from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src import models, schemas
from src.database import get_db
from src.services.track_service import upsert_track_from_event

router = APIRouter()


@router.post("/api/rawevents", response_model=schemas.RawEventResponse, status_code=status.HTTP_201_CREATED)
def create_event(event: schemas.RawEventCreate, db: Session = Depends(get_db)):
    """Save a raw event and immediately upsert a track stub if a video_id exists."""
    db_event = models.RawEvent(**event.model_dump())

    db.add(db_event)
    db.commit()
    db.refresh(db_event)

    upsert_track_from_event(db, db_event)
    return db_event
