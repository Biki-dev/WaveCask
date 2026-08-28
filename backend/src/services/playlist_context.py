"""Context-specific playlist builders for time-of-day and commute favorites."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def build_late_night_rows(db: Session, limit: int = 30):
    query = text("""
        WITH late_night_songs AS (
            SELECT
                t.video_id,
                t.artist,
                t.song,
                COALESCE(t.implicit_score, 0) AS implicit_score,
                COUNT(re.id) AS intentional_plays,
                (COUNT(re.id) * 0.5 + COALESCE(t.implicit_score, 0) * 0.5) AS mix_score
            FROM tracks t
            JOIN raw_events re ON t.video_id = re.video_id
            WHERE re.event_type = 'play'
              AND re.is_autoplay = FALSE
              AND (
                    EXTRACT(HOUR FROM re.timestamp AT TIME ZONE 'UTC') >= 21
                 OR EXTRACT(HOUR FROM re.timestamp AT TIME ZONE 'UTC') < 4
              )
            GROUP BY t.video_id, t.artist, t.song, t.implicit_score
        )
        SELECT *
        FROM late_night_songs
        ORDER BY mix_score DESC, intentional_plays DESC, implicit_score DESC, video_id
        LIMIT :limit
    """)
    return db.execute(query, {"limit": limit}).mappings().all()


def build_commute_rows(db: Session, limit: int = 30):
    query = text("""
        WITH commute_songs AS (
            SELECT
                t.video_id,
                t.artist,
                t.song,
                COALESCE(t.implicit_score, 0) AS implicit_score,
                COUNT(re.id) AS intentional_plays,
                (COUNT(re.id) * 0.5 + COALESCE(t.implicit_score, 0) * 0.5) AS mix_score
            FROM tracks t
            JOIN raw_events re ON t.video_id = re.video_id
            JOIN sessions s ON re.session_id = s.session_id
            WHERE re.event_type = 'play'
              AND re.is_autoplay = FALSE
              AND s.is_long_session = TRUE
            GROUP BY t.video_id, t.artist, t.song, t.implicit_score
        )
        SELECT *
        FROM commute_songs
        ORDER BY mix_score DESC, intentional_plays DESC, implicit_score DESC, video_id
        LIMIT :limit
    """)
    return db.execute(query, {"limit": limit}).mappings().all()


def build_all_time_rows(db: Session, limit: int = 30):
    query = text("""
        SELECT
            t.video_id,
            t.artist,
            t.song,
            COALESCE(t.implicit_score, 0) AS implicit_score,
            COALESCE(t.replay_count, 0) AS intentional_plays,
            COALESCE(t.implicit_score, 0) AS mix_score
        FROM tracks t
        WHERE t.is_music = TRUE
          AND t.implicit_score IS NOT NULL
        ORDER BY COALESCE(t.implicit_score, 0) DESC, COALESCE(t.replay_count, 0) DESC, t.video_id
        LIMIT :limit
    """)
    return db.execute(query, {"limit": limit}).mappings().all()
