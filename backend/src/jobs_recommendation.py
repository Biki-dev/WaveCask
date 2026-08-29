"""
jobs_recommendation.py
-----------------------
Batch computation jobs for the WaveCask recommendation engine.

All functions accept a SQLAlchemy Session and are designed to be called from
the nightly scheduler (classify_tracks_nightly in jobs.py) or from the
/api/playlists/recommendation-models/refresh endpoint.

Execution order matters:
  1. rebuild_engagement()            – needs raw_events
  2. fit_track_clusters()            – needs audio_embedding
  3. rebuild_session_features()      – needs sessions + raw_events
  4. rebuild_taste_profile()         – needs engagement_score_norm
  5. persist recommendation playlists – needs taste profile + clusters
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

import numpy as np
from sklearn.cluster import MiniBatchKMeans
from sqlalchemy import text
from sqlalchemy.orm import Session

from src import models
from src.services.recommendation_math import unit_vector

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# MiniBatchKMeans cluster fitting
# ─────────────────────────────────────────────────────────────────────────────

def fit_track_clusters(db: Session, requested_k: int = 8) -> str | None:
    """
    Fit MiniBatchKMeans on unit-normalised audio embeddings of all eligible
    music tracks, persist the cluster assignments to track_clusters, and
    denormalise cluster_id back onto tracks.

    Returns a hex version string (used as the model fingerprint in playlists),
    or None if there are fewer than 2 eligible tracks.
    """
    rows = db.execute(text("""
        SELECT video_id, audio_embedding::text AS embedding
        FROM tracks
        WHERE is_music = TRUE
          AND audio_embedding IS NOT NULL
          AND processing_status IN ('embedding_done', 'completed')
    """)).mappings().all()

    parsed: list[tuple[str, np.ndarray]] = []
    for r in rows:
        vec = unit_vector(r["embedding"])
        if vec is not None:
            parsed.append((r["video_id"], vec))

    if len(parsed) < 2:
        logger.warning("fit_track_clusters: only %d eligible tracks – skipping", len(parsed))
        return None

    # Cap k so we never request more clusters than tracks
    k = max(2, min(requested_k, int(np.sqrt(len(parsed))) + 1, len(parsed)))
    matrix = np.asarray([vec for _, vec in parsed], dtype=np.float32)

    model = MiniBatchKMeans(
        n_clusters=k,
        random_state=42,
        batch_size=512,
        n_init=10,
    )
    labels = model.fit_predict(matrix)

    # Stable version fingerprint based on date + data shape
    version = hashlib.sha256(
        (
            datetime.now(timezone.utc).strftime("%Y-%m-%d")
            + f":{len(parsed)}:{k}"
        ).encode()
    ).hexdigest()[:16]

    db.execute(text("DELETE FROM track_clusters"))

    for index, ((video_id, _), label) in enumerate(zip(parsed, labels)):
        centroid = model.cluster_centers_[label]
        centroid_norm = np.linalg.norm(centroid)
        distance = float(
            1.0 - np.dot(matrix[index], centroid) / (centroid_norm + 1e-8)
        )
        db.add(
            models.TrackCluster(
                video_id=video_id,
                cluster_id=int(label),
                cluster_version=version,
                distance_to_centroid=distance,
            )
        )

    db.flush()

    # Denormalise cluster_id back onto tracks for fast filtering
    db.execute(text("""
        UPDATE tracks t
        SET cluster_id = c.cluster_id
        FROM track_clusters c
        WHERE c.video_id = t.video_id
    """))

    db.commit()
    logger.info(
        "fit_track_clusters: k=%d tracks=%d version=%s", k, len(parsed), version
    )
    return version


# ─────────────────────────────────────────────────────────────────────────────
# Session co-occurrence rebuild
# ─────────────────────────────────────────────────────────────────────────────

def rebuild_session_features(db: Session) -> int:
    """
    Rebuild session_track_stats and track_cooccurrence from raw_events.

    Co-occurrence is directed (source → target) with a 20-position window to
    prevent very long sessions from making every track co-occur with every
    other.  Returns the number of co-occurrence pairs written.
    """
    # ── session_track_stats ──────────────────────────────────────────────────
    db.execute(text("DELETE FROM session_track_stats"))
    db.execute(text("""
        INSERT INTO session_track_stats (session_id, video_id, position, intentional)
        SELECT
            session_id,
            video_id,
            ROW_NUMBER() OVER (
                PARTITION BY session_id
                ORDER BY MIN(timestamp)
            )::int - 1,
            BOOL_OR(event_type = 'play' AND NOT is_autoplay)
        FROM raw_events
        WHERE video_id IS NOT NULL
        GROUP BY session_id, video_id
    """))

    # ── co-occurrence pairs ──────────────────────────────────────────────────
    db.execute(text("DELETE FROM track_cooccurrence"))

    pairs = db.execute(text("""
        SELECT
            a.video_id AS source_video_id,
            b.video_id AS target_video_id,
            COUNT(*)::int AS count
        FROM session_track_stats a
        JOIN session_track_stats b
          ON a.session_id = b.session_id
         AND a.video_id   <> b.video_id
         AND b.position   > a.position
         AND b.position   - a.position <= 20
        WHERE a.intentional = TRUE OR b.intentional = TRUE
        GROUP BY a.video_id, b.video_id
    """)).mappings().all()

    totals = dict(
        db.execute(text("""
            SELECT video_id, COUNT(DISTINCT session_id)::float AS sessions
            FROM session_track_stats
            GROUP BY video_id
        """)).all()
    )

    total_sessions = float(
        db.execute(text("SELECT COUNT(*) FROM sessions")).scalar_one() or 1
    )

    for row in pairs:
        source_sessions = max(float(totals.get(row["source_video_id"], 1.0)), 1.0)
        target_sessions = max(float(totals.get(row["target_video_id"], 1.0)), 1.0)
        conditional = row["count"] / source_sessions
        lift = conditional / (target_sessions / total_sessions)
        db.add(
            models.TrackCooccurrence(
                source_video_id=row["source_video_id"],
                target_video_id=row["target_video_id"],
                cooccurrence_count=row["count"],
                conditional_probability=conditional,
                lift=lift,
            )
        )

    db.commit()
    logger.info("rebuild_session_features: %d cooccurrence pairs written", len(pairs))
    return len(pairs)
