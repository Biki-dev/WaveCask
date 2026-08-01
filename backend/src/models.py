from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
try:
    from pgvector.sqlalchemy import Vector
    _has_pgvector = True
except ImportError:
    _has_pgvector = False
from src.database import Base

class RawEvent(Base):
    __tablename__ = "raw_events"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(String, index=True, nullable=True)
    title = Column(String, nullable=False)
    channel = Column(String, index=True, nullable=False)
    event_type = Column(String, index=True, nullable=False)
    session_id = Column(String, index=True, nullable=False)
    tab_id = Column(Integer, nullable=False)
    device_id = Column(String, index=True, nullable=False)
    position_seconds = Column(Float, nullable=False)
    video_duration_seconds = Column(Float, nullable=True)
    is_autoplay = Column(Boolean, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)

class SessionSummary(Base):
    __tablename__ = "sessions"

    session_id = Column(String, primary_key=True, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    duration_seconds = Column(Float, nullable=False)
    is_long_session = Column(Boolean, nullable=False)
    avg_position_seconds = Column(Float, nullable=False)
    video_count = Column(Integer, nullable=False)

    raw_events = relationship(
        "RawEvent",
        primaryjoin="RawEvent.session_id == SessionSummary.session_id",
        foreign_keys="[RawEvent.session_id]",
        viewonly=True,
    )


class Track(Base):
    __tablename__ = "tracks"

    video_id = Column(String, primary_key=True, index=True)

    raw_title = Column(String, nullable=False)
    cache_key = Column(String, index=True, nullable=False) 
    channel = Column(String, nullable=False)
    duration_seconds = Column(Float, nullable=True)
    is_music = Column(Boolean, nullable=False, default=False)
    classification_source = Column(String, nullable=True)  # "layer1", "layer2", "layer3"
    artist = Column(String, nullable=False, default="Unknown")
    song = Column(String, nullable=False, default="Unknown")
    genre = Column(String, nullable=False, default="Unknown")
    release_year = Column(String, nullable=False, default="Unknown")
    audio_embedding = Column(Vector(512) if _has_pgvector else Text, nullable=True, default=None)
    implicit_score = Column(Float, nullable=True, default=None)
    replay_count = Column(Integer, nullable=False, default=0)
    max_position_reached = Column(Float, nullable=True, default=None)
    early_skipped = Column(Boolean, nullable=False, default=False)
    # Pipeline lifecycle
    processing_status = Column(
        String, nullable=False, default="pending_classification", index=True
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TrackMetadata(Base):
    __tablename__ = "metadata"

    cache_key = Column(String, primary_key=True, index=True)
    raw_title = Column(String, nullable=False)
    artist = Column(String, nullable=False, default="Unknown")
    song = Column(String, nullable=False, default="Unknown")
    genre = Column(String, nullable=False, default="Unknown")
    release_year = Column(String, nullable=False, default="Unknown")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
