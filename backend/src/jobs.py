"""
nightly job
 ├── Phase 1 · backfill stubs from raw_events
 ├── Phase 2 · classify_pending_tracks  (L1→L2→L3)  → status='classified'
 └── Phase 3 · embed_classified_tracks
              query: is_music=True AND status='classified'
              for each track:
                ├── download 5-sec audio clip (yt-dlp, shared audio_utils)
                ├── run OpenL3 → 512-dim vector (mean-pooled over frames)
                ├── store in audio_embedding (pgvector literal '[0.x, ...]')
                ├── set processing_status = 'embedding_done'
                └── on ANY error → status = 'failed'  +  temp file cleaned up
    Phase 4 · refresh implicit scores from raw_events for embedding_done tracks
    Phase 5 · enrich_completed_tracks → status='completed'
"""


import logging
from datetime import datetime
from sqlalchemy import text
from src.database import SessionLocal
from src.tracks_service import (
    classify_pending_tracks,
    embed_classified_tracks,
    enrich_completed_tracks,
    refresh_implicit_track_scores,
)
from src.playlists_service import create_mix_playlist, create_mood_playlists, create_context_playlists

logger = logging.getLogger(__name__)

def sync_sessions_nightly():
    logger.info("Starting nightly sync of sessions from raw_events...")
    db = SessionLocal()
    try:
        query = text("""
            INSERT INTO sessions (
                session_id, 
                start_time, 
                end_time, 
                duration_seconds, 
                is_long_session, 
                avg_position_seconds, 
                video_count
            )
            SELECT 
                session_id,
                MIN(timestamp) as start_time,
                MAX(timestamp) as end_time,
                EXTRACT(EPOCH FROM (MAX(timestamp) - MIN(timestamp))) as duration_seconds,
                (EXTRACT(EPOCH FROM (MAX(timestamp) - MIN(timestamp))) > 1800) as is_long_session,
                AVG(position_seconds) as avg_position_seconds,
                COUNT(DISTINCT video_id) as video_count
            FROM raw_events
            GROUP BY session_id
            ON CONFLICT (session_id) DO UPDATE SET
                start_time = EXCLUDED.start_time,
                end_time = EXCLUDED.end_time,
                duration_seconds = EXCLUDED.duration_seconds,
                is_long_session = EXCLUDED.is_long_session,
                avg_position_seconds = EXCLUDED.avg_position_seconds,
                video_count = EXCLUDED.video_count;
        """)
        
        # Execute query
        db.execute(query)
        db.commit()
        logger.info("Successfully completed nightly sync of sessions.")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error during nightly sessions sync: {e}")
    finally:
        db.close()


def classify_tracks_nightly():
    """
    Five-phase nightly job:
      1. Backfill track stubs from raw_events (catches any events that arrived
         before the upsert hook existed, or that had no video_id at the time).
      2. Run 3-layer classification on all pending tracks.
      3. Generate OpenL3 audio embeddings for all newly confirmed music tracks
         (is_music=True, processing_status='classified').
        4. Refresh implicit engagement scores for embedded music tracks
            (is_music=True, processing_status='embedding_done').
        5. Enrich metadata via LLM for all newly embedded music tracks
         (is_music=True, processing_status='embedding_done').
    """
    logger.info("Starting nightly track pipeline...")
    db = SessionLocal()
    try:
        # ── Phase 1: backfill stubs for any raw_events not yet in tracks ──────
        backfill_query = text("""
            INSERT INTO tracks (
                video_id,
                raw_title,
                cache_key,
                channel,
                duration_seconds,
                is_music,
                classification_source,
                artist,
                song,
                genre,
                release_year,
                replay_count,
                early_skipped,
                processing_status,
                created_at,
                updated_at
            )
            SELECT DISTINCT ON (video_id)
                video_id,
                title                                              AS raw_title,
                regexp_replace(lower(title), '[^a-z0-9 ]', '', 'g') AS cache_key,
                channel,
                video_duration_seconds                             AS duration_seconds,
                false                                              AS is_music,
                NULL                                               AS classification_source,
                'Unknown'                                          AS artist,
                'Unknown'                                          AS song,
                'Unknown'                                          AS genre,
                'Unknown'                                          AS release_year,
                0                                                  AS replay_count,
                false                                              AS early_skipped,
                'pending_classification'                           AS processing_status,
                NOW()                                              AS created_at,
                NOW()                                              AS updated_at
            FROM raw_events
            WHERE video_id IS NOT NULL
            ORDER BY video_id, timestamp DESC
            ON CONFLICT (video_id) DO UPDATE SET
                -- Metadata columns: always keep fresh from raw_events
                raw_title        = EXCLUDED.raw_title,
                cache_key        = EXCLUDED.cache_key,
                channel          = EXCLUDED.channel,
                duration_seconds = COALESCE(EXCLUDED.duration_seconds, tracks.duration_seconds),
                updated_at       = NOW()
                --     Classification columns intentionally excluded:
                --     is_music, classification_source, processing_status,
                --     artist, song, genre, release_year
                --     are ONLY written by the classifier pipeline.
        """)

        db.execute(backfill_query)
        db.commit()
        logger.info("Phase 1 done: track stubs backfilled from raw_events.")

        # ── Phase 2: classify all pending tracks ──────────────────────────────
        count = classify_pending_tracks(db)
        logger.info(f"Phase 2 done: classified {count} pending tracks.")

        # ── Phase 3: embed confirmed music tracks (is_music=True, classified) ─
        embedded = embed_classified_tracks(db)
        logger.info(f"Phase 3 done: embedded {embedded} music tracks.")

        # ── Phase 4: refresh implicit engagement scores for embedded tracks ──
        scored = refresh_implicit_track_scores(db)
        logger.info(f"Phase 4 done: refreshed implicit scores for {scored} tracks.")

        # ── Phase 5: generate mood playlists from embeddings + implicit score ─
        mood_playlists = create_mood_playlists(db)
        logger.info(f"Phase 5 done: created {len(mood_playlists)} mood playlists.")

        # ── Phase 6: enrich metadata via LLM (is_music=True, embedding_done) ──
        enriched = enrich_completed_tracks(db)
        logger.info(f"Phase 6 done: enriched {enriched} music tracks.")

        # ── Phase 7: generate nightly mix playlists ─────────────────────────
        now = datetime.now()
        windows = [
            {
                "name": f"Today Mix - {now.date().isoformat()}",
                "window_type": "today",
            },
            {
                "name": f"{now.strftime('%A')} Mix - {now.date().isoformat()}",
                "window_type": "day_of_week",
                "day_of_week": now.isoweekday() % 7,
            },
            {
                "name": f"{now.strftime('%B %Y')} Mix - {now.date().isoformat()}",
                "window_type": "month",
                "month": now.month,
                "year": now.year,
            },
        ]

        created_playlists = 0
        for window in windows:
            playlist, rows = create_mix_playlist(
                db,
                name=window["name"],
                window_type=window["window_type"],
                day_of_week=window.get("day_of_week"),
                month=window.get("month"),
                year=window.get("year"),
            )
            if playlist:
                created_playlists += 1
                logger.info(
                    "Phase 7 created playlist id=%s name=%s tracks=%s",
                    playlist.id,
                    playlist.name,
                    len(rows),
                )
            else:
                logger.info(
                    "Phase 7 skipped: no tracks matched window_type=%s",
                    window["window_type"],
                )

        logger.info(f"Phase 7 done: created {created_playlists} nightly mix playlists.")

        # ── Phase 8: generate context playlists (night / commute / all-time) ─
        context_playlists = create_context_playlists(db)
        logger.info(f"Phase 8 done: created {len(context_playlists)} context playlists.")

    except Exception as e:
        db.rollback()
        logger.error(f"Error during nightly track pipeline: {e}")
    finally:
        db.close()

