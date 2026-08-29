"""
recommendation_repository.py
-----------------------------
Database-heavy functions for the WaveCask recommendation engine.

Functions here are designed to run inside a single nightly job (one Session
per function, commit at the end of each logical phase) so that failures are
localised and the raw event log remains the source of truth.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from src import models
from src.services.recommendation_math import unit_vector, weighted_centroid

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Engagement rebuild
# ─────────────────────────────────────────────────────────────────────────────

def rebuild_engagement(db: Session, now: datetime | None = None) -> int:
    """
    Rebuild track_engagement from scratch using raw_events, then denormalize
    key columns back onto the tracks table.

    The engagement_score is a robust cross-track percentile (winsorized at
    p01/p99) so no single heavy-replay track dominates every playlist.

    Returns the number of rows inserted into track_engagement.
    """
    now = now or datetime.now(timezone.utc)

    db.execute(text("DELETE FROM track_engagement"))

    db.execute(
        text("""
            INSERT INTO track_engagement (
                video_id,
                play_count,
                intentional_play_count,
                ended_count,
                skip_count,
                session_count,
                total_watch_seconds,
                completion_ratio,
                skip_rate,
                recency_score,
                engagement_score,
                preference,
                updated_at
            )
            WITH per_track AS (
                SELECT
                    re.video_id,
                    COUNT(*) FILTER (WHERE re.event_type = 'play')::int               AS play_count,
                    COUNT(*) FILTER (WHERE re.event_type = 'play'
                                      AND NOT re.is_autoplay)::int                    AS intentional_play_count,
                    COUNT(*) FILTER (WHERE re.event_type = 'ended')::int              AS ended_count,
                    COUNT(*) FILTER (
                        WHERE re.event_type IN ('pause', 'seeked')
                          AND re.position_seconds < 10
                          AND NOT re.is_autoplay
                    )::int                                                             AS skip_count,
                    COUNT(DISTINCT re.session_id)::int                                AS session_count,
                    COALESCE(SUM(GREATEST(re.delta_seconds, 0)), 0)::double precision AS watch_seconds,
                    MAX(re.video_duration_seconds)::double precision                  AS duration_seconds,
                    MAX(re.timestamp)
                        FILTER (WHERE re.event_type = 'play'
                                  AND NOT re.is_autoplay)                             AS last_played_at
                FROM raw_events re
                WHERE re.video_id IS NOT NULL
                GROUP BY re.video_id
            ),
            raw AS (
                SELECT
                    p.*,
                    LEAST(1.0, GREATEST(0.0,
                         CASE WHEN p.duration_seconds > 0
                              THEN p.watch_seconds / p.duration_seconds
                              ELSE 0 END
                    )) AS completion_ratio_raw,
                    LEAST(1.0, GREATEST(0.0,
                        p.skip_count::double precision
                            / GREATEST(p.intentional_play_count, 1)
                    )) AS skip_rate_raw,
                    EXP(
                        -GREATEST(0.0,
                            EXTRACT(EPOCH FROM (:now - p.last_played_at)) / 86400.0
                        ) / 30.0
                    ) AS recency_raw
                FROM per_track p
            ),
            scored AS (
                SELECT
                    r.*,
                    (  0.45 * r.completion_ratio_raw
                     + 0.25 * (1.0 - r.skip_rate_raw)
                     + 0.20 * LEAST(1.0, LN(1 + r.intentional_play_count) / LN(21))
                     + 0.10 * r.recency_raw
                    ) AS raw_engagement
                FROM raw r
            ),
            bounds AS (
                SELECT
                    percentile_cont(0.01) WITHIN GROUP (ORDER BY raw_engagement) AS p01,
                    percentile_cont(0.99) WITHIN GROUP (ORDER BY raw_engagement) AS p99
                FROM scored
            )
            SELECT
                s.video_id,
                s.play_count,
                s.intentional_play_count,
                s.ended_count,
                s.skip_count,
                s.session_count,
                s.watch_seconds,
                s.completion_ratio_raw,
                s.skip_rate_raw,
                s.recency_raw,
                CASE
                    WHEN b.p99 > b.p01
                    THEN LEAST(1.0, GREATEST(0.0,
                             (s.raw_engagement - b.p01) / (b.p99 - b.p01)
                          ))
                    ELSE 0.5
                END,
                (s.ended_count + 2.0) / (s.ended_count + s.skip_count + 4.0),
                NOW()
            FROM scored s
            CROSS JOIN bounds b
        """),
        {"now": now},
    )

    # Denormalize key signals back onto tracks for fast candidate filtering
    db.execute(text("""
        UPDATE tracks t
        SET
            engagement_score_norm = e.engagement_score,
            completion_ratio      = e.completion_ratio,
            skip_rate             = e.skip_rate,
            preference            = e.preference,
            last_played_at        = (
                SELECT MAX(re.timestamp)
                FROM raw_events re
                WHERE re.video_id = t.video_id
                  AND re.event_type = 'play'
                  AND NOT re.is_autoplay
            )
        FROM track_engagement e
        WHERE e.video_id = t.video_id
    """))

    db.commit()
    count = db.execute(text("SELECT COUNT(*) FROM track_engagement")).scalar_one()
    logger.info("rebuild_engagement: %d rows written", count)
    return count


# ─────────────────────────────────────────────────────────────────────────────
# Taste profile
# ─────────────────────────────────────────────────────────────────────────────

def rebuild_taste_profile(db: Session, profile_key: str = "global") -> int:
    """
    Build a weighted centroid over positively-engaged music tracks and persist
    it as a TasteProfile row.  Returns the number of tracks that contributed.
    """
    rows = db.execute(text("""
        SELECT
            t.video_id,
            t.genre,
            t.cluster_id,
            t.audio_embedding::text AS embedding,
            COALESCE(t.engagement_score_norm, 0.0) AS engagement,
            COALESCE(t.completion_ratio, 0.0)      AS completion,
            COALESCE(t.skip_rate, 0.0)             AS skip_rate
        FROM tracks t
        WHERE t.is_music = TRUE
          AND t.audio_embedding IS NOT NULL
          AND t.processing_status IN ('embedding_done', 'completed')
          AND COALESCE(t.engagement_score_norm, 0.0) >= 0.35
    """)).mappings().all()

    vectors: list = []
    weights: list = []
    genre_weight: dict[str, float] = defaultdict(float)
    cluster_weight: dict[str, float] = defaultdict(float)

    for row in rows:
        vector = unit_vector(row["embedding"])
        if vector is None:
            continue

        weight = max(0.05, float(row["engagement"]))
        weight *= 0.7 + 0.3 * float(row["completion"])
        weight *= 1.0 - 0.5 * float(row["skip_rate"])

        vectors.append(vector)
        weights.append(weight)
        genre_weight[(row["genre"] or "Unknown")] += weight
        if row["cluster_id"] is not None:
            cluster_weight[str(row["cluster_id"])] += weight

    centroid = weighted_centroid(vectors, weights)
    if centroid is None:
        logger.warning(
            "rebuild_taste_profile: no eligible vectors; profile '%s' not updated", profile_key
        )
        return 0

    genre_total = sum(genre_weight.values()) or 1.0
    cluster_total = sum(cluster_weight.values()) or 1.0

    profile = db.get(models.TasteProfile, profile_key)
    if profile is None:
        profile = models.TasteProfile(profile_key=profile_key)
        db.add(profile)

    profile.embedding = centroid.tolist()
    profile.genre_weights = {k: v / genre_total for k, v in genre_weight.items()}
    profile.cluster_weights = {k: v / cluster_total for k, v in cluster_weight.items()}
    profile.positive_track_count = len(vectors)

    db.commit()
    logger.info(
        "rebuild_taste_profile: %d tracks contributed to '%s'", len(vectors), profile_key
    )
    return len(vectors)


# ─────────────────────────────────────────────────────────────────────────────
# Vector candidate retrieval
# ─────────────────────────────────────────────────────────────────────────────

def vector_candidates(db: Session, profile_vector: list[float], limit: int = 300):
    """
    Return up to `limit` eligible tracks ordered by ascending cosine distance
    from `profile_vector`.  The vector literal is passed as a text parameter
    to avoid ORM type-resolution issues with the pgvector import fallback.
    """
    vector_literal = "[" + ",".join(map(str, profile_vector)) + "]"
    return db.execute(
        text("""
            SELECT
                video_id,
                artist,
                song,
                genre,
                release_year,
                COALESCE(engagement_score_norm, 0.0) AS engagement,
                COALESCE(replay_count, 0)            AS replay_count,
                audio_embedding::text                AS embedding,
                1.0 - (audio_embedding <=> CAST(:vector AS vector)) AS vector_similarity
            FROM tracks
            WHERE is_music = TRUE
              AND audio_embedding IS NOT NULL
              AND processing_status IN ('embedding_done', 'completed')
            ORDER BY audio_embedding <=> CAST(:vector AS vector)
            LIMIT :limit
        """),
        {"vector": vector_literal, "limit": limit},
    ).mappings().all()
