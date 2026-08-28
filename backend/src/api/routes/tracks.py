from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src import models, schemas
from src.classifier.audio_embedding import extract_and_store_embedding
from src.database import SessionLocal, get_db
from src.services.track_service import (
    embed_classified_tracks,
    enrich_completed_tracks,
)

router = APIRouter()


def _run_all_embedding_job() -> None:
    db = SessionLocal()
    try:
        embed_classified_tracks(db)
    finally:
        db.close()


def _run_single_embedding_job(video_id: str) -> None:
    db = SessionLocal()
    try:
        extract_and_store_embedding(video_id, db)
    finally:
        db.close()


def _run_all_enrichment_job() -> None:
    db = SessionLocal()
    try:
        enrich_completed_tracks(db)
    finally:
        db.close()


@router.get("/api/tracks", response_model=list[schemas.TrackResponse])
def list_tracks(
    status_filter: str | None = None,
    db: Session = Depends(get_db),
):
    """List all tracks. Optionally filter by processing status."""
    q = db.query(models.Track)
    if status_filter:
        q = q.filter(models.Track.processing_status == status_filter)
    return q.all()


@router.get("/api/tracks/{video_id}", response_model=schemas.TrackResponse)
def get_track(video_id: str, db: Session = Depends(get_db)):
    track = db.query(models.Track).filter(models.Track.video_id == video_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    return track


@router.post("/api/tracks/embed", status_code=status.HTTP_202_ACCEPTED)
def trigger_embedding(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    background_tasks.add_task(_run_all_embedding_job)
    return {"message": "Embedding job started for all classified music tracks"}


@router.post("/api/tracks/{video_id}/embed", status_code=status.HTTP_202_ACCEPTED)
def trigger_single_embedding(video_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    track = db.query(models.Track).filter(models.Track.video_id == video_id).first()
    if not track:
        raise HTTPException(status_code=404, detail=f"Track '{video_id}' not found")
    if not track.is_music:
        raise HTTPException(
            status_code=400,
            detail=f"Track '{video_id}' is not classified as music (is_music=False). Embedding skipped.",
        )
    background_tasks.add_task(_run_single_embedding_job, video_id)
    return {"message": f"Embedding job started for video_id={video_id}"}


@router.post("/api/tracks/enrich", status_code=status.HTTP_202_ACCEPTED)
def trigger_metadata_enrichment(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    background_tasks.add_task(_run_all_enrichment_job)
    return {"message": "Metadata enrichment job started for all embedded tracks"}
