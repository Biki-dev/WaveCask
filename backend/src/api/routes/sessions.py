from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src import models, schemas
from src.database import get_db

router = APIRouter()


@router.get("/api/sessions", response_model=list[schemas.SessionSummaryResponse])
def list_sessions(db: Session = Depends(get_db)):
    return db.query(models.SessionSummary).all()


@router.get("/api/sessions/{session_id}", response_model=schemas.SessionSummaryResponse)
def get_session(session_id: str, db: Session = Depends(get_db)):
    session = (
        db.query(models.SessionSummary)
        .filter(models.SessionSummary.session_id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
