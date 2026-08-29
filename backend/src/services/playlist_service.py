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
    load_existing_mood_playlists,
    load_existing_playlist_rows,
    merge_playlist_rows,
    parse_audio_embedding,
    parse_release_year,
    playlist_profile,
    score_playlist_match,
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


def _persist_playlist_from_rows(db: Session, *, name: str, window_type: str, window_label: str, rows):
    if not rows:
        return None

    playlist = _find_playlist_by_identity(db, name=name, window_type=window_type, window_label=window_label)
    if playlist:
        db.query(models.PlaylistTrack).filter(models.PlaylistTrack.playlist_id == playlist.id).delete(synchronize_session=False)
        logger.info("Refreshing existing playlist id=%s name=%s.", playlist.id, playlist.name)
    else:
        playlist = models.Playlist(name=name, window_type=window_type, window_label=window_label)
        db.add(playlist)
        db.flush()

    for position, row in enumerate(rows, start=1):
        db.add(
            models.PlaylistTrack(
                playlist_id=playlist.id,
                track_video_id=row["video_id"],
                position=position,
                mix_score=float(row["mix_score"] or 0.0),
                intentional_plays=int(row.get("intentional_plays") or 0),
            )
        )

    db.commit()
    db.refresh(playlist)
    logger.info("Saved playlist id=%s name=%s with %s tracks.", playlist.id, playlist.name, len(rows))
    return playlist


def create_mood_playlists(db: Session):
    """Build simple mood playlists by genre, using existing playlist profiles when available."""
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
                t.created_at,
                t.implicit_score,
                t.audio_embedding::text AS audio_embedding,
                (
                    SELECT re.session_id
                    FROM raw_events re
                    WHERE re.video_id = t.video_id
                      AND re.session_id IS NOT NULL
                    ORDER BY re.timestamp DESC, re.id DESC
                    LIMIT 1
                ) AS latest_session_id
            FROM tracks t
            WHERE t.processing_status IN ('embedding_done', 'completed')
              AND t.audio_embedding IS NOT NULL
              AND COALESCE(t.implicit_score, 0) > 0.1
            """
        )
    ).mappings().all()

    if not query:
        return []

    genre_rows: dict[str, list[dict]] = defaultdict(list)
    for row in query:
        embedding = parse_audio_embedding(row["audio_embedding"])
        if embedding is None:
            continue

        genre = row["genre"] or "Other"
        track_row = {
            "video_id": row["video_id"],
            "mix_score": float(row["implicit_score"] or 0.0),
            "intentional_plays": int(row["replay_count"] or 0),
            "genre": genre,
            "artist": row["artist"] or "Unknown",
            "release_year": row["release_year"],
            "session_id": row["latest_session_id"],
            "embedding": embedding,
        }
        genre_rows[genre].append(track_row)

    existing_playlists = load_existing_mood_playlists(db)
    created_playlists = []

    for genre, rows in genre_rows.items():
        if genre in {"Unknown", "Other"} or len(rows) < 2:
            continue

        existing_rows = load_existing_playlist_rows(db, genre)
        merged_rows = merge_playlist_rows(existing_rows, rows)
        playlist = _persist_playlist_from_rows(
            db,
            name=f"{genre} Mix",
            window_type="mood",
            window_label=genre,
            rows=merged_rows,
        )
        if playlist:
            created_playlists.append(playlist)

    if existing_playlists:
        logger.info("Refreshed %s existing mood profiles.", len(existing_playlists))

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