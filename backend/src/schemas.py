from pydantic import BaseModel, field_validator
from typing import Optional, Literal
from datetime import datetime
import json

class RawEventCreate(BaseModel):
    video_id: Optional[str] = None
    title: str
    channel: str
    event_type: str
    session_id: str
    tab_id: int
    device_id: str
    position_seconds: float
    video_duration_seconds: Optional[float] = None
    is_autoplay: bool
    delta_seconds: float = 0.0
    timestamp: datetime

class RawEventResponse(RawEventCreate):
    id: int

    class Config:
        from_attributes = True

class SessionSummaryResponse(BaseModel):
    session_id: str
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    is_long_session: bool
    avg_position_seconds: float
    video_count: int

    class Config:
        from_attributes = True

class TrackResponse(BaseModel):
    video_id: str
    raw_title: str
    cache_key: str
    channel: str
    duration_seconds: Optional[float]
    total_watch_seconds: float
    is_music: bool
    classification_source: Optional[str]
    artist: str
    song: str
    genre: str
    release_year: str
    audio_embedding: Optional[list[float]] = None
    implicit_score: Optional[float]
    replay_count: int
    max_position_reached: Optional[float]
    early_skipped: bool
    processing_status: str
    created_at: datetime
    updated_at: datetime

    @field_validator("audio_embedding", mode="before")
    @classmethod
    def _parse_pgvector(cls, v):
        if v is None:
            return None
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                return [float(x) for x in stripped[1:-1].split(",") if x.strip()]
            return json.loads(stripped)
        raise ValueError(f"Cannot parse audio_embedding value: {v!r}")

    class Config:
        from_attributes = True


class PlaylistMixCreate(BaseModel):
    name: Optional[str] = None
    window_type: Literal["today", "day_of_week", "month", "date_range"]
    day_of_week: Optional[int] = None
    month: Optional[int] = None
    year: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    limit: int = 30
    play_weight: float = 0.5
    implicit_weight: float = 0.5


class PlaylistTrackResponse(BaseModel):
    position: int
    mix_score: float
    intentional_plays: int
    track: TrackResponse

    class Config:
        from_attributes = True


class PlaylistResponse(BaseModel):
    id: int
    name: str
    window_type: str
    window_label: Optional[str]
    created_at: datetime
    tracks: list[PlaylistTrackResponse]

    class Config:
        from_attributes = True


class PlaylistSummaryResponse(BaseModel):
    id: int
    name: str
    window_type: str
    window_label: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation engine schemas
# ─────────────────────────────────────────────────────────────────────────────

class RecommendationRequest(BaseModel):
    limit: int = 30

    @field_validator("limit")
    @classmethod
    def valid_limit(cls, value: int) -> int:
        if not 1 <= value <= 100:
            raise ValueError("limit must be between 1 and 100")
        return value


class RadioRequest(RecommendationRequest):
    seed_video_id: str


class AlsoLikedRequest(RecommendationRequest):
    seed_video_ids: list[str]


class RecommendationTrainResponse(BaseModel):
    clusters_version: Optional[str]
    engagement_tracks: int
    cooccurrence_pairs: int
    taste_profile_tracks: int

