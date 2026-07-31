"""
Tracks Service
--------------
Handles:
  1. Upserting new track rows from raw_events (called on every new raw event)
  2. Running the 3-layer classification pipeline on pending tracks
"""

import re
import logging
from sqlalchemy.orm import Session
from sqlalchemy import text

from src import models
from src.classifier.pipeline import run_pipeline

logger = logging.getLogger(__name__)


def _make_cache_key(raw_title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", raw_title.lower()).strip()


def upsert_track_from_event(db: Session, event: models.RawEvent) -> None:
    if not event.video_id:
        return

    existing = db.query(models.Track).filter(
        models.Track.video_id == event.video_id
    ).first()

    if existing:
        # Update metadata that may have improved (e.g. better title resolved later)
        existing.raw_title = event.title
        existing.cache_key = _make_cache_key(event.title)
        existing.channel = event.channel
        if event.video_duration_seconds is not None:
            existing.duration_seconds = event.video_duration_seconds
        db.commit()
        return

    track = models.Track(
        video_id=event.video_id,
        raw_title=event.title,
        cache_key=_make_cache_key(event.title),
        channel=event.channel,
        duration_seconds=event.video_duration_seconds,
    )
    db.add(track)
    db.commit()
    logger.info(f"New track stub created: video_id={event.video_id}")



def classify_pending_tracks(db: Session) -> int:
    pending = (
        db.query(models.Track)
        .filter(models.Track.processing_status == "pending_classification")
        .all()
    )

    if not pending:
        logger.info("No pending tracks to classify.")
        return 0

    logger.info(f"Classifying {len(pending)} pending tracks...")
    processed = 0

    for track in pending:
        try:
            result = run_pipeline(
                video_id=track.video_id,
                raw_title=track.raw_title,
                channel=track.channel,
                duration_seconds=track.duration_seconds,
            )

            track.is_music = result.is_music
            track.classification_source = result.classification_source
            track.artist = result.artist
            track.song = result.song
            track.genre = result.genre
            track.release_year = result.release_year
            track.processing_status = "classified"

            db.commit()
            processed += 1
            logger.info(
                f"Classified video_id={track.video_id}: "
                f"is_music={result.is_music} source={result.classification_source}"
            )

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to classify video_id={track.video_id}: {e}")

    logger.info(f"Classification complete. {processed}/{len(pending)} tracks classified.")
    return processed
