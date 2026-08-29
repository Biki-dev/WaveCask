"""Playlist workflow orchestrator.

The public API remains stable while the logic is delegated to focused helper
modules under the services package.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from src import models
from src.services.playlist_context import build_all_time_rows, build_commute_rows, build_late_night_rows
from src.services.playlist_mix import build_mix_rows, window_label_from_request
from src.services.playlist_mood import (
    clamp01,
    load_existing_mood_playlists,
    load_existing_playlist_rows,
    merge_playlist_rows,
    mood_track_score,
    parse_audio_embedding,
    parse_release_year,
    playlist_profile,
    recency_score,
    score_playlist_match,
    select_diverse_mood_rows,
)

logger = logging.getLogger(__name__)


def _find_playlist_by_identity(db: Session, *, name: str, window_type: str, window_label: str):
    return (
        db.query(models.Playlist)
        .filter(
            models.Playlist.name == name,
            models.Playlist.window_type == window_type,
            models.Playlist.window_label == window_label,
        )
        .first()
    )


def replace_playlist_from_rows(
    db: Session, *, name: str, window_type: str, window_label: str, rows: list[dict]
):
    playlist = _find_playlist_by_identity(
        db,
        name=name,
        window_type=window_type,
        window_label=window_label,
    )
    if playlist is None:
        if not rows:
            return None
        playlist = models.Playlist(
            name=name,
            window_type=window_type,
            window_label=window_label,
            algorithm="mood_genre_v2",
            model_version="mood-v2",
        )
        db.add(playlist)
        db.flush()
    else:
        db.query(models.PlaylistTrack).filter(
            models.PlaylistTrack.playlist_id == playlist.id
        ).delete(synchronize_session=False)
        playlist.algorithm = "mood_genre_v2"
        playlist.model_version = "mood-v2"

    for position, row in enumerate(rows, start=1):
        db.add(
            models.PlaylistTrack(
                playlist_id=playlist.id,
                track_video_id=row["video_id"],
                position=position,
                mix_score=float(row["mix_score"]),
                intentional_plays=int(row.get("intentional_plays", 0)),
                reason=row.get("reason"),
                score_components=row.get("score_components"),
            )
        )

    db.commit()
    db.refresh(playlist)
    logger.info("Saved playlist id=%s name=%s with %s tracks.", playlist.id, playlist.name, len(rows))
    return playlist


def _persist_playlist_from_rows(db: Session, *, name: str, window_type: str, window_label: str, rows):
    return replace_playlist_from_rows(
        db, name=name, window_type=window_type, window_label=window_label, rows=rows or []
    )


def create_mood_playlists(db: Session):
    """Build deterministic mood playlists by genre with atomic replacement and diversity selection."""
    existing_mood_playlists = (
        db.query(models.Playlist).filter(models.Playlist.window_type == "mood").all()
    )
    existing_labels = {p.window_label for p in existing_mood_playlists if p.window_label}

    query = db.execute(
        text(
            """
            SELECT
                t.video_id,
                t.artist,
                t.song,
                t.genre,
                t.release_year,
                t.replay_count,
                t.engagement_score_norm,
                t.completion_ratio,
                t.skip_rate,
                t.last_played_at,
                t.preference,
                t.audio_embedding::text AS audio_embedding
            FROM tracks t
            WHERE t.is_music = TRUE
              AND t.processing_status IN ('embedding_done', 'completed')
              AND t.audio_embedding IS NOT NULL
            """
        )
    ).mappings().all()

    if not query:
        # Clear all existing mood playlists if no tracks match
        for label in existing_labels:
            name = "Unclassified Mix" if label == "Unclassified" else f"{label} Mix"
            replace_playlist_from_rows(
                db, name=name, window_type="mood", window_label=label, rows=[]
            )
        return []

    genre_rows: dict[str, list[dict]] = defaultdict(list)
    unclassified_candidates: list[dict] = []

    for row in query:
        embedding = parse_audio_embedding(row["audio_embedding"])
        if embedding is None:
            continue

        raw_genre = (row["genre"] or "").strip()
        is_known = bool(raw_genre) and raw_genre.lower() not in {"unknown", "other"}

        track_data = dict(row)
        track_data["embedding_quality"] = 1.0

        if is_known:
            genre_rows[raw_genre].append(track_data)
        else:
            unclassified_candidates.append(track_data)

    created_playlists = []
    updated_labels: set[str] = set()

    for genre, rows in genre_rows.items():
        if len(rows) < 2:
            unclassified_candidates.extend(rows)
            continue

        scored_rows = []
        for row in rows:
            pref = clamp01(
                row.get("preference")
                if row.get("preference") is not None
                else row.get("engagement_score_norm")
            )
            comp = clamp01(row.get("completion_ratio"))
            skip_q = 1.0 - clamp01(row.get("skip_rate"))
            rec = recency_score(row.get("last_played_at"))
            components = {
                "preference": pref,
                "completion": comp,
                "skip_quality": skip_q,
                "recency": rec,
                "metadata_confidence": 1.0,
                "embedding_quality": 1.0,
            }
            base_score = mood_track_score(row)
            scored_rows.append(
                {
                    "video_id": row["video_id"],
                    "artist": row["artist"],
                    "song": row["song"],
                    "genre": genre,
                    "base_score": base_score,
                    "intentional_plays": int(row.get("replay_count") or 0),
                    "reason": f"mood_genre: genre={genre}, score={base_score:.3f}",
                    "score_components": components,
                }
            )

        selected = select_diverse_mood_rows(scored_rows, limit=30)
        playlist = replace_playlist_from_rows(
            db,
            name=f"{genre} Mix",
            window_type="mood",
            window_label=genre,
            rows=selected,
        )
        if playlist and selected:
            created_playlists.append(playlist)
            updated_labels.add(genre)

    if unclassified_candidates:
        scored_unclassified = []
        for row in unclassified_candidates:
            pref = clamp01(
                row.get("preference")
                if row.get("preference") is not None
                else row.get("engagement_score_norm")
            )
            comp = clamp01(row.get("completion_ratio"))
            skip_q = 1.0 - clamp01(row.get("skip_rate"))
            rec = recency_score(row.get("last_played_at"))
            known_genre = (row.get("genre") or "Unknown").strip().lower() not in {"unknown", "other", ""}
            meta_conf = 1.0 if known_genre else 0.25

            components = {
                "preference": pref,
                "completion": comp,
                "skip_quality": skip_q,
                "recency": rec,
                "metadata_confidence": meta_conf,
                "embedding_quality": 1.0,
            }
            base_score = mood_track_score(row)
            scored_unclassified.append(
                {
                    "video_id": row["video_id"],
                    "artist": row["artist"],
                    "song": row["song"],
                    "genre": row.get("genre") or "Unknown",
                    "base_score": base_score,
                    "intentional_plays": int(row.get("replay_count") or 0),
                    "reason": f"mood_genre: genre=Unclassified, score={base_score:.3f}",
                    "score_components": components,
                }
            )

        selected = select_diverse_mood_rows(scored_unclassified, limit=30)
        playlist = replace_playlist_from_rows(
            db,
            name="Unclassified Mix",
            window_type="mood",
            window_label="Unclassified",
            rows=selected,
        )
        if playlist and selected:
            created_playlists.append(playlist)
            updated_labels.add("Unclassified")

    # Clear any pre-existing mood playlists that were not updated in this cycle
    stale_labels = existing_labels - updated_labels
    for stale_label in stale_labels:
        name = "Unclassified Mix" if stale_label == "Unclassified" else f"{stale_label} Mix"
        replace_playlist_from_rows(
            db, name=name, window_type="mood", window_label=stale_label, rows=[]
        )

    return created_playlists


def create_mix_playlist(
    db: Session,
    *,
    name: str | None,
    window_type: str,
    limit: int = 30,
    play_weight: float = 0.5,
    implicit_weight: float = 0.5,
    day_of_week: int | None = None,
    month: int | None = None,
    year: int | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
):
    if window_type == "day_of_week" and day_of_week is None:
        raise ValueError("day_of_week is required for window_type='day_of_week'.")
    if window_type == "month" and month is None:
        raise ValueError("month is required for window_type='month'.")
    if window_type == "date_range" and (start_date is None or end_date is None):
        raise ValueError("start_date and end_date are required for window_type='date_range'.")

    rows = build_mix_rows(
        db,
        window_type=window_type,
        limit=limit,
        play_weight=play_weight,
        implicit_weight=implicit_weight,
        day_of_week=day_of_week,
        month=month,
        year=year,
        start_date=start_date,
        end_date=end_date,
    )
    if not rows:
        return None, []

    label = window_label_from_request(window_type, day_of_week, month, year, start_date, end_date)
    playlist_name = name or label
    playlist = _find_playlist_by_identity(
        db,
        name=playlist_name,
        window_type=window_type,
        window_label=label,
    )

    if playlist:
        db.query(models.PlaylistTrack).filter(models.PlaylistTrack.playlist_id == playlist.id).delete(synchronize_session=False)
        logger.info("Refreshing existing mix playlist id=%s name=%s.", playlist.id, playlist.name)
    else:
        playlist = models.Playlist(name=playlist_name, window_type=window_type, window_label=label)
        db.add(playlist)
        db.flush()

    for position, row in enumerate(rows, start=1):
        db.add(
            models.PlaylistTrack(
                playlist_id=playlist.id,
                track_video_id=row["video_id"],
                position=position,
                mix_score=float(row["mix_score"] or 0.0),
                intentional_plays=int(row["intentional_plays"] or 0),
            )
        )

    db.commit()
    db.refresh(playlist)
    logger.info("Saved mix playlist id=%s with %s tracks.", playlist.id, len(rows))
    return playlist, rows


def list_playlists(db: Session):
    return db.query(models.Playlist).order_by(models.Playlist.created_at.desc()).all()


def get_playlist(db: Session, playlist_id: int):
    return db.query(models.Playlist).filter(models.Playlist.id == playlist_id).first()


def create_context_playlists(db: Session):
    created = []

    late_night_rows = build_late_night_rows(db)
    late_playlist = _persist_playlist_from_rows(
        db,
        name="Late Night Mix",
        window_type="time_of_day",
        window_label="Night",
        rows=late_night_rows,
    )
    if late_playlist:
        created.append(late_playlist)

    commute_rows = build_commute_rows(db)
    commute_playlist = _persist_playlist_from_rows(
        db,
        name="Long Drive Mix",
        window_type="context",
        window_label="Commute",
        rows=commute_rows,
    )
    if commute_playlist:
        created.append(commute_playlist)

    all_time_rows = build_all_time_rows(db)
    all_time_playlist = _persist_playlist_from_rows(
        db,
        name="All Time Favorites",
        window_type="all_time",
        window_label="Overall",
        rows=all_time_rows,
    )
    if all_time_playlist:
        created.append(all_time_playlist)

    return created