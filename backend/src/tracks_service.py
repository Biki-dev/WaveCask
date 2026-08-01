"""
Tracks Service
--------------
Handles:
  1. Upserting new track rows from raw_events (called on every new raw event)
  2. Running the 3-layer classification pipeline on pending tracks
  3. Generating and storing OpenL3 audio embeddings for confirmed music tracks
"""

import re
import logging
from sqlalchemy.orm import Session
from sqlalchemy import text

from src import models
from src.classifier.pipeline import run_pipeline
from src.classifier.audio_embedding import extract_and_store_embedding
from src.classifier.metadata_enrichment import enrich_track_metadata

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


def embed_classified_tracks(db: Session) -> int:
    candidates = (
        db.query(models.Track)
        .filter(
            models.Track.is_music == True,
            models.Track.processing_status == "classified",
        )
        .all()
    )

    if not candidates:
        logger.info("No music tracks awaiting embedding.")
        return 0

    logger.info(f"Embedding {len(candidates)} classified music tracks...")
    succeeded = 0

    for track in candidates:
        logger.info(f"Embedding video_id={track.video_id} ...")
        ok = extract_and_store_embedding(track.video_id, db)
        if ok:
            succeeded += 1
            logger.info(f"Embedding done: video_id={track.video_id}")
        else:
            logger.warning(f"Embedding failed: video_id={track.video_id}")

    logger.info(
        f"Embedding phase complete. {succeeded}/{len(candidates)} tracks embedded."
    )
    return succeeded


def enrich_completed_tracks(db: Session) -> int:
    candidates = (
        db.query(models.Track)
        .filter(
            models.Track.is_music == True,
            models.Track.processing_status == "embedding_done",
        )
        .all()
    )

    if not candidates:
        logger.info("No tracks awaiting metadata enrichment.")
        return 0

    logger.info(f"Enriching metadata for {len(candidates)} tracks...")
    succeeded = 0

    for track in candidates:
        logger.info(f"Enriching video_id={track.video_id} (cache_key={track.cache_key})...")
        try:
            # Check if cache_key exists in metadata table
            meta_record = (
                db.query(models.TrackMetadata)
                .filter(models.TrackMetadata.cache_key == track.cache_key)
                .first()
            )

            if meta_record:
                logger.info(f"Enrichment: Found cached metadata for cache_key={track.cache_key}")
                track.artist = meta_record.artist
                track.song = meta_record.song
                track.genre = meta_record.genre
                track.release_year = meta_record.release_year
                track.processing_status = "completed"
                db.commit()
                succeeded += 1
                continue

            # Call LLM to enrich
            ok, meta = enrich_track_metadata(
                video_id=track.video_id,
                raw_title=track.raw_title,
                channel=track.channel,
            )

            if ok:
                # 1. Update tracks table
                track.artist = meta["artist"]
                track.song = meta["song"]
                track.genre = meta["genre"]
                track.release_year = meta["release_year"]
                track.processing_status = "completed"

                # 2. Insert into metadata table
                new_meta = models.TrackMetadata(
                    cache_key=track.cache_key,
                    raw_title=track.raw_title,
                    artist=meta["artist"],
                    song=meta["song"],
                    genre=meta["genre"],
                    release_year=meta["release_year"],
                )
                db.add(new_meta)
                db.commit()
                succeeded += 1
                logger.info(f"Enrichment: Saved metadata and updated track for video_id={track.video_id}")
            else:
                raise ValueError("Enrichment API returned failure.")

        except Exception as e:
            db.rollback()
            logger.error(f"Enrichment failed for video_id={track.video_id}: {e}")
            try:
                track.processing_status = "failed"
                db.commit()
            except Exception as db_exc:
                db.rollback()
                logger.error(f"Failed to set status to failed for video_id={track.video_id}: {db_exc}")

    logger.info(f"Metadata enrichment complete. {succeeded}/{len(candidates)} tracks enriched.")
    return succeeded


def enrich_single_track(video_id: str, db: Session) -> bool:
    """
    Enrich metadata for a single track by video_id.
    Useful for manual triggering or retrying failed enrichments.
    """
    track = db.query(models.Track).filter(models.Track.video_id == video_id).first()
    if not track:
        logger.error(f"Enrichment: Track {video_id} not found.")
        return False

    logger.info(f"Enriching single track video_id={track.video_id} (cache_key={track.cache_key})...")
    try:
        meta_record = (
            db.query(models.TrackMetadata)
            .filter(models.TrackMetadata.cache_key == track.cache_key)
            .first()
        )

        if meta_record:
            logger.info(f"Enrichment: Found cached metadata for cache_key={track.cache_key}")
            track.artist = meta_record.artist
            track.song = meta_record.song
            track.genre = meta_record.genre
            track.release_year = meta_record.release_year
            track.processing_status = "completed"
            db.commit()
            return True

        ok, meta = enrich_track_metadata(
            video_id=track.video_id,
            raw_title=track.raw_title,
            channel=track.channel,
        )

        if ok:
            track.artist = meta["artist"]
            track.song = meta["song"]
            track.genre = meta["genre"]
            track.release_year = meta["release_year"]
            track.processing_status = "completed"

            new_meta = models.TrackMetadata(
                cache_key=track.cache_key,
                raw_title=track.raw_title,
                artist=meta["artist"],
                song=meta["song"],
                genre=meta["genre"],
                release_year=meta["release_year"],
            )
            db.add(new_meta)
            db.commit()
            logger.info(f"Enrichment: Saved metadata and updated track for video_id={track.video_id}")
            return True
        else:
            raise ValueError("Enrichment API returned failure.")

    except Exception as e:
        db.rollback()
        logger.error(f"Enrichment failed for video_id={track.video_id}: {e}")
        try:
            track.processing_status = "failed"
            db.commit()
        except Exception as db_exc:
            db.rollback()
            logger.error(f"Failed to set status to failed for video_id={track.video_id}: {db_exc}")
        return False

