"""
playlist_recommendation.py
---------------------------
Hybrid playlist generation service for WaveCask.

build_playlist() is the central scoring function.  It retrieves vector
candidates from PostgreSQL and applies a five-term hybrid score:

    final = 0.55 * vector_similarity
          + 0.15 * metadata_match
          + 0.15 * engagement
          + 0.10 * cooccurrence_affinity
          + 0.05 * novelty
          - 0.20 * repetition_penalty

All component weights are initial values tuned to balance relevance and
diversity for a small single-profile catalogue.  Log them via
playlist_tracks.score_components and adjust through offline evaluation.

persist_recommendation() is idempotent: it upserts by (algorithm, generated_for)
and replaces child playlist_tracks in a single transaction.
"""
from __future__ import annotations

import logging
from collections import Counter

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from src import models
from src.repositories.recommendation_repository import vector_candidates
from src.services.recommendation_math import unit_vector

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Score component helpers
# ─────────────────────────────────────────────────────────────────────────────

def _metadata_match(
    candidate: dict,
    preferred_genres: Counter | None = None,
    seed_genre: str | None = None,
) -> float:
    """
    Soft genre match.  Returns 1.0 for an exact seed-genre match, 0.5 when
    genre is unknown (neutral, not a penalty), or a normalised weight from the
    preferred_genres counter.
    """
    genre = (candidate.get("genre") or "Unknown").strip().lower()
    if seed_genre:
        return 1.0 if genre == seed_genre.strip().lower() else 0.0
    if not preferred_genres or genre == "unknown":
        return 0.5
    return min(1.0, float(preferred_genres.get(genre, 0.0)))


def _novelty_score(candidate: dict, played_ids: set[str]) -> float:
    """1.0 if the track has never been played, 0.0 otherwise."""
    return 0.0 if candidate["video_id"] in played_ids else 1.0


def _repetition_penalty(
    candidate: dict,
    selected_artists: Counter,
    selected_ids: set[str],
    played_ids: set[str],
) -> float:
    """
    Cumulative penalty:
      +1.0  track already selected in this generation run  → hard exclude
      +0.5  artist already has ≥ 2 tracks in this run      → soft penalty
      +0.25 track was played previously                    → soft recency penalty
    """
    penalty = 0.0
    if candidate["video_id"] in selected_ids:
        penalty += 1.0
    if candidate.get("artist") and selected_artists[candidate["artist"]] >= 2:
        penalty += 0.5
    if candidate["video_id"] in played_ids:
        penalty += 0.25
    return min(1.0, penalty)


def _cooccurrence_affinity(
    db: Session, seed_ids: list[str], candidate_id: str
) -> float:
    """
    Max conditional probability of the candidate given any of the seed tracks.
    Returns 0.0 when there are no seeds or no matching co-occurrence rows.
    """
    if not seed_ids:
        return 0.0
    row = db.execute(
        text("""
            SELECT COALESCE(MAX(LEAST(1.0, conditional_probability)), 0.0)
            FROM track_cooccurrence
            WHERE source_video_id = ANY(:seed_ids)
              AND target_video_id = :candidate_id
        """),
        {"seed_ids": seed_ids, "candidate_id": candidate_id},
    ).scalar_one()
    return float(row or 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Core playlist builder
# ─────────────────────────────────────────────────────────────────────────────

def build_playlist(
    db: Session,
    *,
    algorithm: str,
    profile_vector: list[float],
    limit: int = 30,
    seed_ids: list[str] | None = None,
    cluster_id: int | None = None,
    generated_for: str | None = None,
) -> list[dict]:
    """
    Retrieve vector candidates and score them with the hybrid formula.

    Parameters
    ----------
    algorithm:       Label used in score explanations (e.g. 'discover_weekly').
    profile_vector:  L2-normalised 512-dim query vector (taste profile or seed).
    limit:           Maximum number of tracks to return.
    seed_ids:        Track IDs used for co-occurrence affinity and metadata.
    cluster_id:      When set, restricts candidates to the given cluster.
    generated_for:   Informational; not used for scoring.
    """
    seed_ids = seed_ids or []

    # Fetch vector-ordered candidates (wider pool for post-filtering)
    candidates = vector_candidates(db, profile_vector, limit=max(limit * 12, 300))

    # Optional cluster filter
    if cluster_id is not None:
        allowed_ids = set(
            db.execute(
                text("SELECT video_id FROM track_clusters WHERE cluster_id = :cluster_id"),
                {"cluster_id": cluster_id},
            ).scalars().all()
        )
        candidates = [row for row in candidates if row["video_id"] in allowed_ids]

    # Tracks the listener has previously played (for novelty + recency penalty)
    played_ids = set(
        db.execute(
            text("""
                SELECT DISTINCT video_id FROM raw_events
                WHERE video_id IS NOT NULL AND event_type = 'play'
            """)
        ).scalars().all()
    )

    # Genre affinity from seed tracks
    preferred_genres: Counter = Counter()
    if seed_ids:
        for genre_row in db.execute(
            text("""
                SELECT genre, COUNT(*)::float
                FROM tracks
                WHERE video_id = ANY(:seed_ids)
                GROUP BY genre
            """),
            {"seed_ids": seed_ids},
        ).all():
            preferred_genres[(genre_row[0] or "Unknown").lower()] = float(genre_row[1])
        total_genres = sum(preferred_genres.values()) or 1.0
        preferred_genres = Counter({k: v / total_genres for k, v in preferred_genres.items()})

    selected: list[dict] = []
    selected_ids: set[str] = set()
    selected_artists: Counter = Counter()

    for row in candidates:
        vector = unit_vector(row["embedding"])
        if vector is None:
            continue

        video_id = row["video_id"]

        vector_score  = float(np.clip(row["vector_similarity"], 0.0, 1.0))
        meta_score    = _metadata_match(row, preferred_genres)
        engagement    = float(np.clip(row["engagement"], 0.0, 1.0))
        cooc          = _cooccurrence_affinity(db, seed_ids, video_id)
        novelty       = _novelty_score(row, played_ids)
        penalty       = _repetition_penalty(row, selected_artists, selected_ids, played_ids)

        # Hard-exclude exact duplicates
        if penalty >= 1.0:
            continue

        score = (
            0.55 * vector_score
            + 0.15 * meta_score
            + 0.15 * engagement
            + 0.10 * cooc
            + 0.05 * novelty
            - 0.20 * penalty
        )

        selected.append(
            {
                "video_id": video_id,
                "mix_score": round(score, 6),
                "intentional_plays": int(row["replay_count"] or 0),
                "reason": (
                    f"{algorithm}: vector={vector_score:.3f}, "
                    f"metadata={meta_score:.3f}, engagement={engagement:.3f}"
                ),
                "score_components": {
                    "vector": vector_score,
                    "metadata": meta_score,
                    "engagement": engagement,
                    "cooccurrence": cooc,
                    "novelty": novelty,
                    "repetition_penalty": penalty,
                },
            }
        )
        selected_ids.add(video_id)
        selected_artists[row["artist"] or "Unknown"] += 1

        if len(selected) >= limit:
            break

    selected.sort(key=lambda x: x["mix_score"], reverse=True)
    return selected


# ─────────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────────

def persist_recommendation(
    db: Session,
    *,
    name: str,
    algorithm: str,
    model_version: str,
    generated_for: str,
    rows: list[dict],
) -> models.Playlist | None:
    """
    Idempotent upsert of a recommendation playlist.

    Looks up an existing playlist by (algorithm, generated_for).  If found,
    replaces its child playlist_tracks.  If not, creates a new Playlist row.
    All child operations happen in a single transaction.

    Returns the persisted Playlist, or None when rows is empty.
    """
    if not rows:
        return None

    playlist = (
        db.query(models.Playlist)
        .filter(
            models.Playlist.algorithm == algorithm,
            models.Playlist.generated_for == generated_for,
        )
        .first()
    )

    if playlist is None:
        playlist = models.Playlist(
            name=name,
            window_type="recommendation",
            window_label=algorithm,
            algorithm=algorithm,
            model_version=model_version,
            generated_for=generated_for,
        )
        db.add(playlist)
        db.flush()          # get playlist.id
    else:
        playlist.name          = name
        playlist.model_version = model_version
        db.query(models.PlaylistTrack).filter(
            models.PlaylistTrack.playlist_id == playlist.id
        ).delete(synchronize_session=False)

    for position, row in enumerate(rows, 1):
        db.add(
            models.PlaylistTrack(
                playlist_id=playlist.id,
                track_video_id=row["video_id"],
                position=position,
                mix_score=row["mix_score"],
                intentional_plays=row.get("intentional_plays", 0),
                reason=row.get("reason"),
                score_components=row.get("score_components"),
            )
        )

    db.commit()
    db.refresh(playlist)
    logger.info(
        "persist_recommendation: algorithm=%s generated_for=%s tracks=%d playlist_id=%s",
        algorithm,
        generated_for,
        len(rows),
        playlist.id,
    )
    return playlist
