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
            WHERE t.is_music = TRUE
              AND re.event_type = 'play'
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


def build_commute_rows(
    db: Session,
    limit: int = 30,
    play_weight: float = 0.5,
    implicit_weight: float = 0.5,
):
    """Build a commute playlist with balanced, configurable ranking signals.

    Play counts are log-normalized within the candidate set so highly replayed songs
    do not overwhelm the bounded implicit score. Both weights retain the previous
    50/50 default while allowing future playlist tuning.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if play_weight < 0 or implicit_weight < 0 or play_weight + implicit_weight == 0:
        raise ValueError("weights must be non-negative and not both zero")

    query = text("""
        WITH commute_songs AS (
            SELECT
                t.video_id,
                t.artist,
                t.song,
                COALESCE(t.implicit_score, 0) AS implicit_score,
                COUNT(re.id) AS intentional_plays
            FROM tracks t
            JOIN raw_events re ON t.video_id = re.video_id
            JOIN sessions s ON re.session_id = s.session_id
            WHERE t.is_music = TRUE
              AND re.event_type = 'play'
              AND re.is_autoplay = FALSE
              AND s.is_long_session = TRUE
            GROUP BY t.video_id, t.artist, t.song, t.implicit_score
        ), normalized_songs AS (
            SELECT
                commute_songs.*,
                CASE
                    WHEN MAX(intentional_plays) OVER () > 0 THEN
                        LN(1 + intentional_plays)::DOUBLE PRECISION
                        / LN(1 + MAX(intentional_plays) OVER ())
                    ELSE 0
                END AS normalized_intentional_plays,
                LEAST(GREATEST(implicit_score, 0), 1) AS normalized_implicit_score
            FROM commute_songs
        )
        SELECT
            video_id,
            artist,
            song,
            implicit_score,
            intentional_plays,
            (
                :play_weight * normalized_intentional_plays
                + :implicit_weight * normalized_implicit_score
            ) AS mix_score
        FROM normalized_songs
        ORDER BY mix_score DESC, intentional_plays DESC, implicit_score DESC, video_id
        LIMIT :limit
    """)
    return db.execute(
        query,
        {
            "limit": limit,
            "play_weight": play_weight,
            "implicit_weight": implicit_weight,
        },
    ).mappings().all()


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
