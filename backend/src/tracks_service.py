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
import math
from sqlalchemy.orm import Session
from sqlalchemy import text

from src import models
from src.classifier.pipeline import run_pipeline
from src.classifier.audio_embedding import extract_and_store_embedding
from src.classifier.metadata_enrichment import enrich_track_metadata

logger = logging.getLogger(__name__)


def _make_cache_key(raw_title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", raw_title.lower()).strip()


def _compute_implicit_score(
    duration_seconds: float | None,
    total_watch_seconds: float | None,
    replay_count: int,
    early_skipped: bool,
) -> float:
    duration = float(duration_seconds or 0.0)
    watch_time = float(total_watch_seconds or 0.0)

    completion_ratio = 0.0
    if duration > 0:
        completion_ratio = max(0.0, min(watch_time / duration, 1.0))

    replay_bonus = 0.5 * math.log1p(max(replay_count, 0))
    skip_penalty = 0.8 if early_skipped else 0.0

    score = completion_ratio + replay_bonus - skip_penalty
    return round(max(0.0, min(score, 1.0)), 4)


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


def refresh_implicit_track_scores(db: Session) -> int:
    query = text("""
        SELECT
            video_id,
            MAX(video_duration_seconds) AS duration,
            MAX(position_seconds) AS max_position_reached,
            COALESCE(SUM(delta_seconds), 0) AS total_watch_seconds,
            COUNT(CASE WHEN event_type = 'play' AND is_autoplay = FALSE THEN 1 END) AS replay_count,
            CASE
                WHEN MAX(CASE WHEN event_type IN ('pause','seeked') AND position_seconds < 10 THEN 1 ELSE 0 END) = 1
                     AND MAX(CASE WHEN event_type = 'ended' THEN 1 ELSE 0 END) = 0
                THEN TRUE ELSE FALSE
            END AS early_skipped
        FROM raw_events
        WHERE video_id IN (
            SELECT video_id FROM tracks WHERE processing_status = 'embedding_done'
        )
        GROUP BY video_id
    """)

    rows = db.execute(query).mappings().all()
    if not rows:
        logger.info("No embedded tracks awaiting implicit score refresh.")
        return 0

    updated = 0
    for row in rows:
        track = db.query(models.Track).filter(models.Track.video_id == row["video_id"]).first()
        if not track:
            continue

        track.max_position_reached = row["max_position_reached"]
        track.total_watch_seconds = float(row["total_watch_seconds"] or 0.0)
        track.replay_count = int(row["replay_count"] or 0)
        track.early_skipped = bool(row["early_skipped"])
        track.implicit_score = _compute_implicit_score(
            duration_seconds=row["duration"],
            total_watch_seconds=row["total_watch_seconds"],
            replay_count=track.replay_count,
            early_skipped=track.early_skipped,
        )
        updated += 1

    db.commit()
    logger.info(f"Implicit score refresh complete. Updated {updated}/{len(rows)} tracks.")
    return updated


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

