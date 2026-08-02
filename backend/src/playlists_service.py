import ast
import logging
from datetime import datetime, date, timezone
from collections import Counter

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from src import models

logger = logging.getLogger(__name__)


def _window_label_from_request(
    window_type: str,
    day_of_week: int | None,
    month: int | None,
    year: int | None,
    start_date: datetime | None,
    end_date: datetime | None,
) -> str:
    if window_type == "today":
        return "Today Mix"
    if window_type == "day_of_week" and day_of_week is not None:
        labels = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        return f"{labels[day_of_week]} Mix"
    if window_type == "month" and month is not None:
        suffix = f" {year}" if year else ""
        return f"{date(2000, month, 1).strftime('%B')}{suffix} Mix"
    if window_type == "date_range" and start_date and end_date:
        return f"Mix {start_date.date().isoformat()} to {end_date.date().isoformat()}"
    return "Mix"


def _build_window_filter(
    window_type: str,
    params: dict,
) -> tuple[str, dict]:
    clauses = ["re.event_type = 'play'", "re.is_autoplay = FALSE", "re.video_id IS NOT NULL"]
    sql_params: dict = {"limit": params["limit"], "play_weight": params["play_weight"], "implicit_weight": params["implicit_weight"]}

    if window_type == "today":
        clauses.append("re.timestamp >= CURRENT_DATE")
        clauses.append("re.timestamp < CURRENT_DATE + INTERVAL '1 day'")
    elif window_type == "day_of_week":
        clauses.append("EXTRACT(DOW FROM re.timestamp) = :day_of_week")
        sql_params["day_of_week"] = params["day_of_week"]
    elif window_type == "month":
        clauses.append("EXTRACT(MONTH FROM re.timestamp) = :month")
        sql_params["month"] = params["month"]
        if params.get("year") is not None:
            clauses.append("EXTRACT(YEAR FROM re.timestamp) = :year")
            sql_params["year"] = params["year"]
    elif window_type == "date_range":
        clauses.append("re.timestamp >= :start_date")
        clauses.append("re.timestamp < :end_date")
        sql_params["start_date"] = params["start_date"]
        sql_params["end_date"] = params["end_date"]
    else:
        raise ValueError(f"Unsupported window_type: {window_type}")

    return " AND ".join(clauses), sql_params


def build_mix_rows(
    db: Session,
    *,
    window_type: str,
    limit: int,
    play_weight: float,
    implicit_weight: float,
    day_of_week: int | None = None,
    month: int | None = None,
    year: int | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
):
    where_clause, sql_params = _build_window_filter(
        window_type,
        {
            "limit": limit,
            "play_weight": play_weight,
            "implicit_weight": implicit_weight,
            "day_of_week": day_of_week,
            "month": month,
            "year": year,
            "start_date": start_date,
            "end_date": end_date,
        },
    )

    query = text(f"""
        SELECT
            t.video_id,
            t.artist,
            t.song,
            COALESCE(t.implicit_score, 0) AS implicit_score,
            COUNT(re.id) AS intentional_plays,
            (COUNT(re.id) * :play_weight + COALESCE(t.implicit_score, 0) * :implicit_weight) AS mix_score
        FROM tracks t
        JOIN raw_events re ON t.video_id = re.video_id
        WHERE {where_clause}
        GROUP BY t.video_id, t.artist, t.song, t.implicit_score
        ORDER BY mix_score DESC, intentional_plays DESC, COALESCE(t.implicit_score, 0) DESC, t.video_id
        LIMIT :limit
    """)

    rows = db.execute(query, sql_params).mappings().all()
    return rows


def _parse_audio_embedding(raw_embedding) -> np.ndarray | None:
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


def _cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    if left.size == 0 or right.size == 0:
        return -1.0

    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm == 0.0 or right_norm == 0.0:
        return -1.0

    return float(np.dot(left, right) / (left_norm * right_norm))


def _track_recency_weight(created_at: datetime | None) -> float:
    if created_at is None:
        return 0.7

    aware_created_at = created_at
    if aware_created_at.tzinfo is None:
        aware_created_at = aware_created_at.replace(tzinfo=timezone.utc)

    age_days = max((datetime.now(timezone.utc) - aware_created_at).total_seconds() / 86400.0, 0.0)
    return float(np.exp(-age_days / 30.0))


def _parse_release_year(value) -> int | None:
    if value is None:
        return None

    text = str(value).strip()
    if len(text) < 4:
        return None

    try:
        year = int(text[:4])
    except ValueError:
        return None

    if year < 1900 or year > datetime.now(timezone.utc).year + 1:
        return None

    return year


def _load_playlist_session_counts(db: Session, playlist_id: int) -> Counter:
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


def _playlist_profile(playlist) -> dict | None:
    embeddings = []
    weights = []
    genres = []
    artists = []
    release_years = []
    created_ats = []

    for entry in playlist.tracks:
        embedding = _parse_audio_embedding(getattr(entry.track, "audio_embedding", None))
        if embedding is None:
            continue

        recency_weight = _track_recency_weight(getattr(entry, "created_at", None))
        score_weight = 1.0 + min(max(float(entry.mix_score or 0.0), 0.0), 1.0)
        combined_weight = recency_weight * score_weight

        embeddings.append(embedding)
        weights.append(combined_weight)
        genres.append((getattr(entry.track, "genre", None) or "Unknown").strip() or "Unknown")
        artists.append((getattr(entry.track, "artist", None) or "Unknown").strip() or "Unknown")
        release_year = _parse_release_year(getattr(entry.track, "release_year", None))
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


def _load_existing_mood_playlists(db: Session):
    playlists = (
        db.query(models.Playlist)
        .filter(models.Playlist.window_type == "mood")
        .all()
    )

    playlist_data = []
    for playlist in playlists:
        profile = _playlist_profile(playlist)
        if profile is None:
            continue

        playlist_data.append(
            {
                "playlist": playlist,
                "profile": profile,
                "session_counts": _load_playlist_session_counts(db, playlist.id),
                "label": (playlist.window_label or playlist.name or "").strip(),
            }
        )

    return playlist_data


def _score_playlist_match(track_row: dict, playlist_item: dict) -> float:
    playlist = playlist_item["playlist"]
    profile = playlist_item["profile"]
    track_embedding = track_row["embedding"]
    track_genre = track_row["genre"]
    track_score = float(track_row.get("mix_score") or 0.0)

    embedding_similarity = _cosine_similarity(track_embedding, profile["centroid"])
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
    track_release_year = _parse_release_year(track_row.get("release_year"))
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
    recency_boost = _track_recency_weight(latest_created_at)
    popularity_boost = min(profile["track_count"] / 10.0, 1.0)

    if playlist.window_label and playlist.window_label.lower() == f"{track_genre.lower()} mix":
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


def _load_existing_playlist_rows(db: Session, window_label: str):
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


def _merge_playlist_rows(existing_rows, new_rows):
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


def create_mood_playlists(db: Session):
    try:
        import hdbscan  # pyright: ignore[reportMissingImports]
    except ImportError:
        logger.warning("HDBSCAN is not installed; skipping mood playlist generation.")
        return []

    query = text("""
        SELECT
            video_id,
            artist,
            song,
            genre,
            release_year,
            replay_count,
            created_at,
                        (
                                SELECT re.session_id
                                FROM raw_events re
                                WHERE re.video_id = t.video_id
                                    AND re.session_id IS NOT NULL
                                ORDER BY re.timestamp DESC, re.id DESC
                                LIMIT 1
                        ) AS latest_session_id,
            implicit_score,
            audio_embedding::text AS audio_embedding
        FROM tracks
        WHERE processing_status = 'embedding_done'
          AND audio_embedding IS NOT NULL
          AND COALESCE(implicit_score, 0) > 0.1
    """)

    tracks = db.execute(query).mappings().all()

    genre_rows: dict[str, list[dict]] = {}
    existing_mood_playlists = _load_existing_mood_playlists(db)
    existing_rows_by_playlist_id: dict[int, list[dict]] = {
        item["playlist"].id: _load_existing_playlist_rows(
            db,
            item["playlist"].window_label or item["playlist"].name,
        )
        for item in existing_mood_playlists
    }
    assigned_rows_by_playlist_id: dict[int, list[dict]] = {playlist.id: [] for playlist in (item["playlist"] for item in existing_mood_playlists)}
    unassigned_rows: list[dict] = []

    for row in tracks:
        embedding = _parse_audio_embedding(row["audio_embedding"])
        if embedding is None:
            continue

        genre = row["genre"] or "Other"

        track_row = {
            "video_id": row["video_id"],
            "mix_score": float(row["implicit_score"] or 0.0),
            "intentional_plays": 0,
            "genre": genre,
            "artist": row["artist"] or "Unknown",
            "release_year": row["release_year"],
            "session_id": row["latest_session_id"],
            "embedding": embedding,
        }

        best_playlist_id = None
        best_score = -1.0

        for item in existing_mood_playlists:
            score = _score_playlist_match(track_row, item)
            if score > best_score:
                best_score = score
                best_playlist_id = item["playlist"].id

        if best_playlist_id is not None and best_score >= 0.72:
            assigned_rows_by_playlist_id.setdefault(best_playlist_id, []).append(track_row)
            continue

        genre_rows.setdefault(genre, []).append(track_row)
        unassigned_rows.append(track_row)

    created_playlists = []

    for item in existing_mood_playlists:
        playlist = item["playlist"]
        new_rows = assigned_rows_by_playlist_id.get(playlist.id, [])
        if not new_rows:
            continue

        merged_rows = _merge_playlist_rows(
            existing_rows_by_playlist_id.get(playlist.id, []),
            new_rows,
        )
        updated_playlist = _persist_playlist_from_rows(
            db,
            name=playlist.name,
            window_type="mood",
            window_label=playlist.window_label or playlist.name,
            rows=merged_rows,
        )
        if updated_playlist:
            created_playlists.append(updated_playlist)

    if len(unassigned_rows) >= 3:
        clusterer = hdbscan.HDBSCAN(min_cluster_size=3, metric="euclidean")
        cluster_vectors = np.asarray(
            [np.concatenate([row["embedding"], np.asarray([row["mix_score"] * 0.5], dtype=np.float32)]) for row in unassigned_rows],
            dtype=np.float32,
        )
        labels = clusterer.fit_predict(cluster_vectors)

        unique_labels = {label for label in labels if label != -1}
        for label in sorted(unique_labels):
            cluster_indices = np.where(labels == label)[0]
            if len(cluster_indices) < 3:
                continue

            cluster_genres = [unassigned_rows[index]["genre"] for index in cluster_indices]
            known_genres = [genre for genre in cluster_genres if genre not in {"Unknown", "Other"}]
            top_genre = Counter(known_genres).most_common(1)[0][0] if known_genres else "Mood"
            playlist_name = f"{top_genre} Mix"

            probability_scores = getattr(clusterer, "probabilities_", None)
            cluster_rows = []
            for index in cluster_indices:
                cluster_rows.append(
                    {
                        "video_id": unassigned_rows[index]["video_id"],
                        "mix_score": float(probability_scores[index]) if probability_scores is not None else 1.0,
                        "intentional_plays": 0,
                    }
                )

            existing_rows = _load_existing_playlist_rows(db, top_genre)
            merged_rows = _merge_playlist_rows(existing_rows, cluster_rows)
            playlist = _persist_playlist_from_rows(
                db,
                name=playlist_name,
                window_type="mood",
                window_label=top_genre,
                rows=merged_rows,
            )
            if playlist:
                created_playlists.append(playlist)

    if created_playlists:
        logger.info("Saved %s mood playlists.", len(created_playlists))
        return created_playlists

    fallback_genres = sorted(
        (
            (genre, rows)
            for genre, rows in genre_rows.items()
            if genre not in {"Unknown", "Other"} and len(rows) >= 2
        ),
        key=lambda item: (-len(item[1]), item[0].lower()),
    )

    if not fallback_genres:
        logger.debug("Skipping mood playlist generation: not enough tracks per genre yet.")
        return []

    for genre, rows in fallback_genres:
        existing_rows = _load_existing_playlist_rows(db, genre)
        merged_rows = _merge_playlist_rows(existing_rows, rows)
        playlist = _persist_playlist_from_rows(
            db,
            name=f"{genre} Mix",
            window_type="mood",
            window_label=genre,
            rows=merged_rows,
        )
        if playlist:
            created_playlists.append(playlist)

    logger.info("Saved %s mood playlists.", len(created_playlists))
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

    label = _window_label_from_request(window_type, day_of_week, month, year, start_date, end_date)
    playlist_name = name or label
    playlist = _find_playlist_by_identity(
        db,
        name=playlist_name,
        window_type=window_type,
        window_label=label,
    )

    if playlist:
        db.query(models.PlaylistTrack).filter(
            models.PlaylistTrack.playlist_id == playlist.id
        ).delete(synchronize_session=False)
        logger.info("Refreshing existing mix playlist id=%s name=%s.", playlist.id, playlist.name)
    else:
        playlist = models.Playlist(
            name=playlist_name,
            window_type=window_type,
            window_label=label,
        )
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
    return (
        db.query(models.Playlist)
        .filter(models.Playlist.id == playlist_id)
        .first()
    )


def _find_playlist_by_identity(
    db: Session,
    *,
    name: str,
    window_type: str,
    window_label: str,
):
    return (
        db.query(models.Playlist)
        .filter(
            models.Playlist.name == name,
            models.Playlist.window_type == window_type,
            models.Playlist.window_label == window_label,
        )
        .first()
    )


def _persist_playlist_from_rows(
    db: Session,
    *,
    name: str,
    window_type: str,
    window_label: str,
    rows,
):
    if not rows:
        return None

    playlist = _find_playlist_by_identity(
        db,
        name=name,
        window_type=window_type,
        window_label=window_label,
    )

    if playlist:
        db.query(models.PlaylistTrack).filter(
            models.PlaylistTrack.playlist_id == playlist.id
        ).delete(synchronize_session=False)
        logger.info("Refreshing existing playlist id=%s name=%s.", playlist.id, playlist.name)
    else:
        playlist = models.Playlist(
            name=name,
            window_type=window_type,
            window_label=window_label,
        )
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


def create_context_playlists(db: Session):
    created = []

    late_night_rows = build_late_night_rows(db)
    playlist = _persist_playlist_from_rows(
        db,
        name="Late Night Mix",
        window_type="time_of_day",
        window_label="Night",
        rows=late_night_rows,
    )
    if playlist:
        created.append(playlist)

    commute_rows = build_commute_rows(db)
    playlist = _persist_playlist_from_rows(
        db,
        name="Long Drive Mix",
        window_type="context",
        window_label="Commute",
        rows=commute_rows,
    )
    if playlist:
        created.append(playlist)

    all_time_rows = build_all_time_rows(db)
    playlist = _persist_playlist_from_rows(
        db,
        name="All Time Favorites",
        window_type="all_time",
        window_label="Overall",
        rows=all_time_rows,
    )
    if playlist:
        created.append(playlist)

    return created