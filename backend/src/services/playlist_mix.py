"""Playlist-window helpers for building mix playlists from raw event data."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


def window_label_from_request(
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


def build_window_filter(window_type: str, params: dict) -> tuple[str, dict]:
    clauses = ["re.event_type = 'play'", "re.is_autoplay = FALSE", "re.video_id IS NOT NULL"]
    sql_params: dict = {
        "limit": params["limit"],
        "play_weight": params["play_weight"],
        "implicit_weight": params["implicit_weight"],
    }

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
    where_clause, sql_params = build_window_filter(
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

    return db.execute(query, sql_params).mappings().all()
