from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, Numeric, ForeignKey, UniqueConstraint, JSON
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
    # ── Recommendation engine columns ────────────────────────────────────────
    engagement_score_norm = Column(Float, nullable=True)
    completion_ratio      = Column(Float, nullable=False, default=0.0, server_default=text("0.0"))
    skip_rate             = Column(Float, nullable=False, default=0.0, server_default=text("0.0"))
    last_played_at        = Column(DateTime(timezone=True), nullable=True)
    cluster_id            = Column(Integer, nullable=True)
    embedding_norm        = Column(Float, nullable=True)
    preference            = Column(Float, nullable=False, default=0.5, server_default=text("0.5"))

    playlist_entries = relationship(
        "PlaylistTrack",
        back_populates="track",
        cascade="all, delete-orphan",
    )
    engagement = relationship(
        "TrackEngagement",
        back_populates="track",
        uselist=False,
        cascade="all, delete-orphan",
    )


class TrackListeningAttempt(Base):
    """Attempt-level listening records representing individual sessions / tracks plays."""
    __tablename__ = "track_listening_attempts"

    attempt_id              = Column(String, primary_key=True)
    video_id                = Column(String, ForeignKey("tracks.video_id", ondelete="CASCADE"), nullable=False)
    session_id              = Column(String, nullable=True)
    started_at              = Column(DateTime(timezone=True), nullable=False)
    ended_at                = Column(DateTime(timezone=True), nullable=True)
    watched_seconds         = Column(Float, nullable=False, default=0.0)
    duration_seconds        = Column(Float, nullable=True)
    max_position_seconds    = Column(Float, nullable=False, default=0.0)
    completion_ratio        = Column(Float, nullable=False, default=0.0)
    ended_normally          = Column(Boolean, nullable=False, default=False)
    skipped_early           = Column(Boolean, nullable=False, default=False)
    intentional_probability = Column(Float, nullable=False, default=0.5)
    created_at              = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Playlist(Base):
    __tablename__ = "playlists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    window_type = Column(String, nullable=False)
    window_label = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # ── Recommendation engine columns ────────────────────────────────────────
    algorithm     = Column(String, nullable=True, index=True)
    model_version = Column(String, nullable=True)
    generated_for = Column(String, nullable=True)

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
    # ── Recommendation engine columns ────────────────────────────────────────
    reason           = Column(String, nullable=True)
    score_components = Column(JSON, nullable=True)

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


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation engine tables
# ─────────────────────────────────────────────────────────────────────────────

class TrackEngagement(Base):
    """Normalized behavioral aggregates per track, rebuilt nightly from raw_events."""
    __tablename__ = "track_engagement"

    video_id               = Column(String, ForeignKey("tracks.video_id", ondelete="CASCADE"), primary_key=True)
    play_count             = Column(Integer, nullable=False, default=0)
    intentional_play_count = Column(Integer, nullable=False, default=0)
    ended_count            = Column(Integer, nullable=False, default=0)
    skip_count             = Column(Integer, nullable=False, default=0)
    session_count          = Column(Integer, nullable=False, default=0)
    total_watch_seconds    = Column(Float, nullable=False, default=0.0)
    completion_ratio       = Column(Float, nullable=False, default=0.0)
    skip_rate              = Column(Float, nullable=False, default=0.0)
    recency_score          = Column(Float, nullable=False, default=0.0)
    engagement_score       = Column(Float, nullable=False, default=0.0)
    preference             = Column(Float, nullable=False, default=0.5)
    updated_at             = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    track = relationship("Track", back_populates="engagement")


class SessionTrackStat(Base):
    """One row per (session, track) capturing play order and intentionality."""
    __tablename__ = "session_track_stats"

    session_id  = Column(String, ForeignKey("sessions.session_id", ondelete="CASCADE"), primary_key=True)
    video_id    = Column(String, ForeignKey("tracks.video_id", ondelete="CASCADE"), primary_key=True)
    position    = Column(Integer, nullable=False)
    intentional = Column(Boolean, nullable=False, default=False)


class TrackCooccurrence(Base):
    """Directed pair statistics: how often target follows source within 20 positions."""
    __tablename__ = "track_cooccurrence"

    source_video_id         = Column(String, ForeignKey("tracks.video_id", ondelete="CASCADE"), primary_key=True)
    target_video_id         = Column(String, ForeignKey("tracks.video_id", ondelete="CASCADE"), primary_key=True)
    cooccurrence_count      = Column(Integer, nullable=False, default=0)
    conditional_probability = Column(Float, nullable=False, default=0.0)
    lift                    = Column(Float, nullable=False, default=0.0)
    updated_at              = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TrackCluster(Base):
    """MiniBatchKMeans cluster assignment per track, versioned by fit date."""
    __tablename__ = "track_clusters"

    video_id             = Column(String, ForeignKey("tracks.video_id", ondelete="CASCADE"), primary_key=True)
    cluster_id           = Column(Integer, nullable=False, index=True)
    cluster_version      = Column(String, nullable=False, index=True)
    distance_to_centroid = Column(Float, nullable=True)
    updated_at           = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TasteProfile(Base):
    """Aggregated listener preference vector.  profile_key='global' for single-user installs."""
    __tablename__ = "taste_profiles"

    profile_key          = Column(String, primary_key=True)
    embedding            = Column(Vector(512) if _has_pgvector else Text, nullable=False)
    genre_weights        = Column(JSON, nullable=False, default=dict)
    cluster_weights      = Column(JSON, nullable=False, default=dict)
    positive_track_count = Column(Integer, nullable=False, default=0)
    updated_at           = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
