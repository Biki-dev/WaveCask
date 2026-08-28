from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src import models, schemas
from src.database import SessionLocal, get_db
from src.jobs import sync_sessions_nightly, classify_tracks_nightly
from src.services.track_service import enrich_single_track

router = APIRouter()


def _run_single_track_enrichment_job(video_id: str) -> None:
    db = SessionLocal()
    try:
        enrich_single_track(video_id, db)
    finally:
        db.close()


@router.post("/api/sessions/sync", status_code=status.HTTP_202_ACCEPTED)
def trigger_session_sync(background_tasks: BackgroundTasks):
    """Trigger the nightly session sync job manually."""
    background_tasks.add_task(sync_sessions_nightly)
    return {"message": "Session sync job started"}


@router.post("/api/tracks/classify", status_code=status.HTTP_202_ACCEPTED)
def trigger_classification(background_tasks: BackgroundTasks):
    """Manually trigger the pipeline on all pending tracks."""
    background_tasks.add_task(classify_tracks_nightly)
    return {"message": "Track classification started"}


@router.post("/api/tracks/{video_id}/enrich", status_code=status.HTTP_202_ACCEPTED)
def trigger_single_metadata_enrichment(
    video_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    track = db.query(models.Track).filter(models.Track.video_id == video_id).first()
    if not track:
        raise HTTPException(status_code=404, detail=f"Track '{video_id}' not found")
    if not track.is_music:
        raise HTTPException(
            status_code=400,
            detail=f"Track '{video_id}' is not classified as music (is_music=False). Enrichment skipped.",
        )
    background_tasks.add_task(_run_single_track_enrichment_job, video_id)
    return {"message": f"Metadata enrichment job started for video_id={video_id}"}


@router.get("/health")
def health_check():
    return {"status": "ok"}
