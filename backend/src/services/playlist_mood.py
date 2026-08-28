"""Mood-based playlist clustering and profile matching helpers."""

from __future__ import annotations

import ast
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from src import models

logger = logging.getLogger(__name__)


def parse_audio_embedding(raw_embedding) -> np.ndarray | None:
    if raw_embedding is None:
        return None

    if hasattr(raw_embedding, "tolist"):
        raw_embedding = raw_embedding.tolist()
    elif isinstance(raw_embedding, str):
        try:
            raw_embedding = ast.literal_eval(raw_embedding)
        except (SyntaxError, ValueError):
            return None

    try:
        embedding = np.asarray(raw_embedding, dtype=np.float32)
    except (TypeError, ValueError):
        return None

    if embedding.size == 0:
        return None

    norm = float(np.linalg.norm(embedding))
    if norm == 0.0:
        return None

    return embedding / norm


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    if left.size == 0 or right.size == 0:
        return -1.0

    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm == 0.0 or right_norm == 0.0:
        return -1.0

    return float(np.dot(left, right) / (left_norm * right_norm))


def track_recency_weight(created_at: datetime | None) -> float:
    if created_at is None:
        return 0.7

    aware_created_at = created_at
    if aware_created_at.tzinfo is None:
        aware_created_at = aware_created_at.replace(tzinfo=timezone.utc)

    age_days = max((datetime.now(timezone.utc) - aware_created_at).total_seconds() / 86400.0, 0.0)
    return float(np.exp(-age_days / 30.0))


def parse_release_year(value) -> int | None:
    if value is None:
        return None

    text_value = str(value).strip()
    if len(text_value) < 4:
        return None

    try:
        year = int(text_value[:4])
    except ValueError:
        return None

    if year < 1900 or year > datetime.now(timezone.utc).year + 1:
        return None

    return year


def load_playlist_session_counts(db: Session, playlist_id: int) -> Counter:
    rows = db.execute(
        text("""
            SELECT DISTINCT ON (pt.track_video_id)
                re.session_id
            FROM playlist_tracks pt
            JOIN raw_events re ON pt.track_video_id = re.video_id
            WHERE pt.playlist_id = :playlist_id
              AND re.session_id IS NOT NULL
            ORDER BY pt.track_video_id, re.timestamp DESC, re.id DESC
        """),
        {"playlist_id": playlist_id},
    ).mappings().all()

    return Counter(
        str(row["session_id"]).strip()
        for row in rows
        if row["session_id"] is not None and str(row["session_id"]).strip()
    )


def playlist_profile(playlist) -> dict | None:
    embeddings = []
    weights = []
    genres = []
    artists = []
    release_years = []
    created_ats = []

    for entry in playlist.tracks:
        embedding = parse_audio_embedding(getattr(entry.track, "audio_embedding", None))
        if embedding is None:
            continue

        recency_weight = track_recency_weight(getattr(entry, "created_at", None))
        score_weight = 1.0 + min(max(float(entry.mix_score or 0.0), 0.0), 1.0)
        combined_weight = recency_weight * score_weight

        embeddings.append(embedding)
        weights.append(combined_weight)
        genres.append((getattr(entry.track, "genre", None) or "Unknown").strip() or "Unknown")
        artists.append((getattr(entry.track, "artist", None) or "Unknown").strip() or "Unknown")
        release_year = parse_release_year(getattr(entry.track, "release_year", None))
        if release_year is not None:
            release_years.append(release_year)
        created_ats.append(getattr(entry, "created_at", None))

    if not embeddings:
        return None

    embedding_matrix = np.asarray(embeddings, dtype=np.float32)
    weight_vector = np.asarray(weights, dtype=np.float32)
    weight_sum = float(weight_vector.sum())
    if weight_sum == 0.0:
        return None

    centroid = np.average(embedding_matrix, axis=0, weights=weight_vector)
    centroid_norm = float(np.linalg.norm(centroid))
    if centroid_norm == 0.0:
        return None

    genre_counts = Counter(genre for genre in genres if genre not in {"Unknown", "Other"})
    artist_counts = Counter(artist for artist in artists if artist not in {"Unknown", "Other"})
    total_tracks = len(embeddings)
    latest_created_at = max((created_at for created_at in created_ats if created_at is not None), default=None)
    average_release_year = float(np.mean(release_years)) if release_years else None

    return {
        "centroid": centroid / centroid_norm,
        "genre_counts": genre_counts,
        "artist_counts": artist_counts,
        "track_count": total_tracks,
        "latest_created_at": latest_created_at,
        "average_release_year": average_release_year,
    }


def load_existing_mood_playlists(db: Session):
    playlists = (
        db.query(models.Playlist)
        .filter(models.Playlist.window_type == "mood")
        .all()
    )

    playlist_data = []
    for playlist in playlists:
        profile = playlist_profile(playlist)
        if profile is None:
            continue

        playlist_data.append(
            {
                "playlist": playlist,
                "profile": profile,
                "session_counts": load_playlist_session_counts(db, playlist.id),
                "label": (playlist.window_label or playlist.name or "").strip(),
            }
        )

    return playlist_data


def score_playlist_match(track_row: dict, playlist_item: dict) -> float:
    profile = playlist_item["profile"]
    track_embedding = track_row["embedding"]
    track_genre = track_row["genre"]
    track_score = float(track_row.get("mix_score") or 0.0)

    embedding_similarity = cosine_similarity(track_embedding, profile["centroid"])
    if embedding_similarity < 0.0:
        return -1.0

    genre_counts: Counter = profile["genre_counts"]
    genre_total = sum(genre_counts.values())
    genre_affinity = 0.0
    if track_genre not in {"Unknown", "Other"}:
        genre_affinity = (genre_counts.get(track_genre, 0) / genre_total) if genre_total else 0.0

    artist_counts: Counter = profile["artist_counts"]
    artist_total = sum(artist_counts.values())
    artist_affinity = 0.0
    track_artist = (track_row.get("artist") or "Unknown").strip() or "Unknown"
    if track_artist not in {"Unknown", "Other"}:
        artist_affinity = (artist_counts.get(track_artist, 0) / artist_total) if artist_total else 0.0

    release_year_affinity = 0.0
    track_release_year = parse_release_year(track_row.get("release_year"))
    if track_release_year is not None and profile["average_release_year"] is not None:
        release_year_delta = abs(track_release_year - profile["average_release_year"])
        release_year_affinity = float(np.exp(-release_year_delta / 8.0))

    session_counts: Counter = playlist_item["session_counts"]
    session_total = sum(session_counts.values())
    session_affinity = 0.0
    track_session_id = (track_row.get("session_id") or "").strip()
    if track_session_id:
        session_affinity = (session_counts.get(track_session_id, 0) / session_total) if session_total else 0.0

    latest_created_at = profile["latest_created_at"]
    recency_boost = track_recency_weight(latest_created_at)
    popularity_boost = min(profile["track_count"] / 10.0, 1.0)

    if playlist_item["playlist"].window_label and playlist_item["playlist"].window_label.lower() == f"{track_genre.lower()} mix":
        return 1.0

    return (
        0.62 * embedding_similarity
        + 0.20 * genre_affinity
        + 0.08 * artist_affinity
        + 0.04 * release_year_affinity
        + 0.06 * session_affinity
        + 0.02 * recency_boost
        + 0.01 * popularity_boost
        + min(track_score, 1.0) * 0.01
    )


def load_existing_playlist_rows(db: Session, window_label: str):
    playlist = (
        db.query(models.Playlist)
        .filter(
            models.Playlist.window_type == "mood",
            models.Playlist.window_label == window_label,
        )
        .first()
    )
    if not playlist:
        return []

    return [
        {
            "video_id": entry.track_video_id,
            "mix_score": float(entry.mix_score or 0.0),
            "intentional_plays": int(entry.intentional_plays or 0),
        }
        for entry in playlist.tracks
    ]


def merge_playlist_rows(existing_rows, new_rows):
    merged: dict[str, dict] = {}

    for row in existing_rows + new_rows:
        video_id = row["video_id"]
        if video_id not in merged:
            merged[video_id] = {
                "video_id": video_id,
                "mix_score": float(row.get("mix_score") or 0.0),
                "intentional_plays": int(row.get("intentional_plays") or 0),
            }
        else:
            merged[video_id]["mix_score"] = max(
                merged[video_id]["mix_score"],
                float(row.get("mix_score") or 0.0),
            )
            merged[video_id]["intentional_plays"] = max(
                merged[video_id]["intentional_plays"],
                int(row.get("intentional_plays") or 0),
            )

    return sorted(
        merged.values(),
        key=lambda item: (-item["mix_score"], -item["intentional_plays"], item["video_id"]),
    )


def cluster_genres(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["genre"]].append(row)
    return dict(grouped)
