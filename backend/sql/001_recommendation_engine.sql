-- backend/sql/001_recommendation_engine.sql
-- Idempotent migration for WaveCask recommendation engine.
-- Safe to re-run: uses IF NOT EXISTS / IF EXISTS / DO UPDATE guards throughout.

-- ── Indexes on raw_events for efficient engagement queries ─────────────────
CREATE INDEX IF NOT EXISTS ix_raw_events_video_timestamp
    ON raw_events (video_id, timestamp);
CREATE INDEX IF NOT EXISTS ix_raw_events_session_video
    ON raw_events (session_id, video_id);
CREATE INDEX IF NOT EXISTS ix_raw_events_event_type_autoplay
    ON raw_events (event_type, is_autoplay);

-- ── Index on tracks for fast candidate eligibility filtering ───────────────
CREATE INDEX IF NOT EXISTS ix_tracks_recommendable
    ON tracks (is_music, processing_status)
    WHERE is_music = TRUE AND audio_embedding IS NOT NULL;

-- ── Denormalized engagement columns on tracks (mirrors track_engagement) ───
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS engagement_score_norm DOUBLE PRECISION;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS completion_ratio     DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE tracks ALTER COLUMN completion_ratio SET DEFAULT 0;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS skip_rate            DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE tracks ALTER COLUMN skip_rate SET DEFAULT 0;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS last_played_at       TIMESTAMPTZ;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS cluster_id           INTEGER;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS embedding_norm       DOUBLE PRECISION;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS preference           DOUBLE PRECISION NOT NULL DEFAULT 0.5;

-- ── track_listening_attempts: attempt-level aggregate table ───────────────
CREATE TABLE IF NOT EXISTS track_listening_attempts (
    attempt_id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES tracks(video_id) ON DELETE CASCADE,
    session_id TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    watched_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
    duration_seconds DOUBLE PRECISION,
    max_position_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
    completion_ratio DOUBLE PRECISION NOT NULL DEFAULT 0,
    ended_normally BOOLEAN NOT NULL DEFAULT FALSE,
    skipped_early BOOLEAN NOT NULL DEFAULT FALSE,
    intentional_probability DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_attempts_video_started
    ON track_listening_attempts(video_id, started_at DESC);

-- ── track_engagement: normalized behavioral aggregates per track ───────────
CREATE TABLE IF NOT EXISTS track_engagement (
    video_id               TEXT PRIMARY KEY REFERENCES tracks(video_id) ON DELETE CASCADE,
    play_count             INTEGER          NOT NULL DEFAULT 0,
    intentional_play_count INTEGER          NOT NULL DEFAULT 0,
    ended_count            INTEGER          NOT NULL DEFAULT 0,
    skip_count             INTEGER          NOT NULL DEFAULT 0,
    session_count          INTEGER          NOT NULL DEFAULT 0,
    total_watch_seconds    DOUBLE PRECISION NOT NULL DEFAULT 0,
    completion_ratio       DOUBLE PRECISION NOT NULL DEFAULT 0,
    skip_rate              DOUBLE PRECISION NOT NULL DEFAULT 0,
    recency_score          DOUBLE PRECISION NOT NULL DEFAULT 0,
    engagement_score       DOUBLE PRECISION NOT NULL DEFAULT 0,
    preference             DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    updated_at             TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

-- ── session_track_stats: one row per (session, track) with ordering ────────
CREATE TABLE IF NOT EXISTS session_track_stats (
    session_id  TEXT    NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    video_id    TEXT    NOT NULL REFERENCES tracks(video_id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    intentional BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (session_id, video_id)
);
CREATE INDEX IF NOT EXISTS ix_session_track_stats_video ON session_track_stats(video_id);

-- ── track_cooccurrence: directed pair statistics from shared sessions ──────
CREATE TABLE IF NOT EXISTS track_cooccurrence (
    source_video_id        TEXT             NOT NULL REFERENCES tracks(video_id) ON DELETE CASCADE,
    target_video_id        TEXT             NOT NULL REFERENCES tracks(video_id) ON DELETE CASCADE,
    cooccurrence_count     INTEGER          NOT NULL DEFAULT 0,
    conditional_probability DOUBLE PRECISION NOT NULL DEFAULT 0,
    lift                   DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at             TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_video_id, target_video_id),
    CHECK (source_video_id <> target_video_id)
);
CREATE INDEX IF NOT EXISTS ix_track_cooccurrence_source_score
    ON track_cooccurrence(source_video_id, conditional_probability DESC);

-- ── track_clusters: MiniBatchKMeans cluster assignments ───────────────────
CREATE TABLE IF NOT EXISTS track_clusters (
    video_id              TEXT             PRIMARY KEY REFERENCES tracks(video_id) ON DELETE CASCADE,
    cluster_id            INTEGER          NOT NULL,
    cluster_version       TEXT             NOT NULL,
    distance_to_centroid  DOUBLE PRECISION,
    updated_at            TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_track_clusters_cluster ON track_clusters(cluster_version, cluster_id);

-- ── taste_profiles: aggregated listener preference vector ─────────────────
CREATE TABLE IF NOT EXISTS taste_profiles (
    profile_key         TEXT        PRIMARY KEY,
    embedding           vector(512) NOT NULL,
    genre_weights       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    cluster_weights     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    positive_track_count INTEGER    NOT NULL DEFAULT 0,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Extend playlists with recommendation metadata ─────────────────────────
ALTER TABLE playlists ADD COLUMN IF NOT EXISTS algorithm      TEXT;
ALTER TABLE playlists ADD COLUMN IF NOT EXISTS model_version  TEXT;
ALTER TABLE playlists ADD COLUMN IF NOT EXISTS generated_for  TEXT;

-- ── Extend playlist_tracks with explainability fields ─────────────────────
ALTER TABLE playlist_tracks ADD COLUMN IF NOT EXISTS reason           TEXT;
ALTER TABLE playlist_tracks ADD COLUMN IF NOT EXISTS score_components JSONB;

-- ── Unique index for idempotent recommendation playlist upsert ─────────────
CREATE UNIQUE INDEX IF NOT EXISTS uq_playlists_algorithm_generated_for
    ON playlists(algorithm, generated_for)
    WHERE algorithm IS NOT NULL AND generated_for IS NOT NULL;

-- ── HNSW index for fast ANN vector search (create after data is populated) ─
CREATE INDEX IF NOT EXISTS ix_tracks_embedding_hnsw
    ON tracks USING hnsw (audio_embedding vector_cosine_ops)
    WHERE is_music = TRUE AND audio_embedding IS NOT NULL;
