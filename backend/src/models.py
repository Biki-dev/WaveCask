from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, Numeric, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text
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
    delta_seconds = Column(Numeric(10, 2), nullable=False, default=0.0, server_default=text("0.0"))
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
    total_watch_seconds = Column(Numeric(10, 2), nullable=False, default=0.0, server_default=text("0.0"))
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

    playlist_entries = relationship(
        "PlaylistTrack",
        back_populates="track",
        cascade="all, delete-orphan",
    )


class Playlist(Base):
    __tablename__ = "playlists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    window_type = Column(String, nullable=False)
    window_label = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    tracks = relationship(
        "PlaylistTrack",
        back_populates="playlist",
        cascade="all, delete-orphan",
        order_by="PlaylistTrack.position",
    )


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"

    id = Column(Integer, primary_key=True, index=True)
    playlist_id = Column(Integer, ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False, index=True)
    track_video_id = Column(String, ForeignKey("tracks.video_id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    mix_score = Column(Float, nullable=False)
    intentional_plays = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("playlist_id", "position", name="uq_playlist_tracks_playlist_position"),
        UniqueConstraint("playlist_id", "track_video_id", name="uq_playlist_tracks_playlist_video"),
    )

    playlist = relationship("Playlist", back_populates="tracks")
    track = relationship("Track", back_populates="playlist_entries")


class TrackMetadata(Base):
    __tablename__ = "metadata"

    cache_key = Column(String, primary_key=True, index=True)
    raw_title = Column(String, nullable=False)
    artist = Column(String, nullable=False, default="Unknown")
    song = Column(String, nullable=False, default="Unknown")
    genre = Column(String, nullable=False, default="Unknown")
    release_year = Column(String, nullable=False, default="Unknown")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
