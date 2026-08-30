"""
test_playlist_mood.py
---------------------
Unit and integration tests for WaveCask mood/genre playlist implementation.
"""
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import text

from src import models
from src.services.playlist_mood import (
    clamp01,
    recency_score,
    mood_track_score,
    select_diverse_mood_rows,
)
from src.services.playlist_service import (
    _find_playlist_by_identity,
    create_mood_playlists,
    replace_playlist_from_rows,
)


class TestMoodScoringHelpers:
    def test_short_listen_does_not_reach_top_score(self):
        # 20s listen on 300s track: completion ~0.066, skip_rate=1.0, engagement=0.1
        short_listen_row = {
            "genre": "Rock",
            "preference": 0.1,
            "completion_ratio": 0.066,
            "skip_rate": 1.0,
            "last_played_at": datetime.now(timezone.utc),
            "embedding_quality": 1.0,
        }
        score = mood_track_score(short_listen_row)
        assert score < 0.5

    def test_full_completion_scores_above_short_partial_listen(self):
        full_completion = {
            "genre": "Rock",
            "preference": 0.9,
            "completion_ratio": 1.0,
            "skip_rate": 0.0,
            "last_played_at": datetime.now(timezone.utc),
            "embedding_quality": 1.0,
        }
        short_partial = {
            "genre": "Rock",
            "preference": 0.2,
            "completion_ratio": 0.15,
            "skip_rate": 0.85,
            "last_played_at": datetime.now(timezone.utc),
            "embedding_quality": 1.0,
        }
        assert mood_track_score(full_completion) > mood_track_score(short_partial)

    def test_repeated_short_listens_bounded(self):
        # Even with high replay_count, bounded features prevent unbounded score explosion
        row = {
            "genre": "Rock",
            "preference": 0.4,
            "completion_ratio": 0.1,
            "skip_rate": 0.9,
            "replay_count": 100,
            "last_played_at": datetime.now(timezone.utc),
            "embedding_quality": 1.0,
        }
        score = mood_track_score(row)
        assert 0.0 <= score <= 1.0
        assert score < 0.6

    def test_track_not_played_for_90_days_recency_decay(self):
        now = datetime.now(timezone.utc)
        recent_track = {"genre": "Rock", "last_played_at": now, "preference": 0.5, "completion_ratio": 0.5, "skip_rate": 0.0}
        old_track = {"genre": "Rock", "last_played_at": now - timedelta(days=90), "preference": 0.5, "completion_ratio": 0.5, "skip_rate": 0.0}

        assert recency_score(old_track["last_played_at"]) < recency_score(recent_track["last_played_at"])
        assert mood_track_score(recent_track) > mood_track_score(old_track)

    def test_same_score_prefers_artist_diversity(self):
        rows = [
            {"video_id": f"v{i}", "artist": "Artist A", "song": f"s{i}", "base_score": 0.8}
            for i in range(5)
        ] + [
            {"video_id": "v5", "artist": "Artist B", "song": "s5", "base_score": 0.8},
            {"video_id": "v6", "artist": "Artist C", "song": "s6", "base_score": 0.8},
        ]

        selected = select_diverse_mood_rows(rows, limit=5)
        artists = [r["artist"] for r in selected]
        # Artist A should be capped at 3
        assert artists.count("Artist A") <= 3
        assert "Artist B" in artists
        assert "Artist C" in artists

    def test_stale_track_disappears_when_fresh_score_below_cutoff(self):
        rows = [
            {"video_id": "fresh1", "artist": "Artist A", "song": "Song 1", "base_score": 0.9},
            {"video_id": "fresh2", "artist": "Artist B", "song": "Song 2", "base_score": 0.85},
            {"video_id": "stale", "artist": "Artist C", "song": "Stale Song", "base_score": 0.1},
        ]
        # Select top 2
        selected = select_diverse_mood_rows(rows, limit=2)
        selected_ids = [r["video_id"] for r in selected]
        assert "stale" not in selected_ids

    def test_unknown_genre_excluded_from_named_included_in_fallback(self):
        unknown_genre_track = {"genre": "Unknown", "preference": 0.8, "completion_ratio": 0.8, "skip_rate": 0.1}
        named_genre_track = {"genre": "Rock", "preference": 0.8, "completion_ratio": 0.8, "skip_rate": 0.1}

        # Unknown genre gets lower metadata confidence
        assert mood_track_score(unknown_genre_track) < mood_track_score(named_genre_track)

    def test_fewer_than_three_artists_cap_relaxes(self):
        # Candidate pool with only 1 artist
        rows = [
            {"video_id": f"v{i}", "artist": "Solo Artist", "song": f"s{i}", "base_score": 0.8 - i * 0.01}
            for i in range(10)
        ]
        selected = select_diverse_mood_rows(rows, limit=10)
        assert len(selected) == 10

    def test_duplicate_video_id_appears_at_most_once(self):
        rows = [
            {"video_id": "v1", "artist": "Artist A", "song": "Song 1", "base_score": 0.9},
            {"video_id": "v1", "artist": "Artist A", "song": "Song 1 Dup", "base_score": 0.85},
            {"video_id": "v2", "artist": "Artist B", "song": "Song 2", "base_score": 0.8},
        ]
        selected = select_diverse_mood_rows(rows, limit=10)
        selected_ids = [r["video_id"] for r in selected]
        assert len(selected_ids) == len(set(selected_ids))
        assert selected_ids.count("v1") == 1

    def test_empty_candidate_group_policy(self, db_session):
        # Create an existing playlist with child rows
        playlist = models.Playlist(name="Rock Mix", window_type="mood", window_label="Rock")
        db_session.add(playlist)
        db_session.flush()

        track = models.Track(video_id="v_test1", raw_title="Test", cache_key="ck_test1", channel="Ch", is_music=True)
        db_session.add(track)
        db_session.flush()

        db_session.add(models.PlaylistTrack(playlist_id=playlist.id, track_video_id="v_test1", position=1, mix_score=0.9))
        db_session.commit()

        # Replace playlist with empty rows
        replace_playlist_from_rows(db_session, name="Rock Mix", window_type="mood", window_label="Rock", rows=[])

        updated = db_session.query(models.Playlist).filter_by(id=playlist.id).first()
        assert updated is not None
        assert len(updated.tracks) == 0


class TestMixPlaylistIdentity:
    def test_monthly_playlist_reuses_existing_dated_playlist(self, db_session):
        existing = models.Playlist(
            name="August 2026 Mix - 2026-08-29",
            window_type="month",
            window_label="August 2026 Mix",
        )
        db_session.add(existing)
        db_session.flush()
        existing_id = existing.id

        found = _find_playlist_by_identity(
            db_session,
            name="August 2026 Mix",
            window_type="month",
            window_label="August 2026 Mix",
        )

        assert found.id == existing_id
        assert found.name == "August 2026 Mix"
        assert db_session.query(models.Playlist).filter_by(window_type="month").count() == 1


class TestIntegrationMoodPlaylist:
    def test_create_mood_playlists_does_not_retain_stale_membership(self, db_session):
        # Create test track with valid embedding and high engagement
        dummy_embedding = [0.1] * 512
        t1 = models.Track(
            video_id="v_mood1",
            raw_title="Mood Song 1",
            cache_key="ck_mood1",
            channel="Artist 1",
            artist="Artist 1",
            song="Mood Song 1",
            genre="Jazz",
            is_music=True,
            processing_status="completed",
            audio_embedding=dummy_embedding,
            engagement_score_norm=0.9,
            completion_ratio=1.0,
            skip_rate=0.0,
        )
        t2 = models.Track(
            video_id="v_mood2",
            raw_title="Mood Song 2",
            cache_key="ck_mood2",
            channel="Artist 2",
            artist="Artist 2",
            song="Mood Song 2",
            genre="Jazz",
            is_music=True,
            processing_status="completed",
            audio_embedding=dummy_embedding,
            engagement_score_norm=0.8,
            completion_ratio=0.9,
            skip_rate=0.1,
        )
        db_session.add_all([t1, t2])
        db_session.commit()

        # Run 1: Create mood playlists
        playlists_run1 = create_mood_playlists(db_session)
        jazz_pl1 = [p for p in playlists_run1 if p.window_label == "Jazz"]
        assert len(jazz_pl1) == 1
        assert {t.track_video_id for t in jazz_pl1[0].tracks} == {"v_mood1", "v_mood2"}

        # Between runs: lower t1's engagement and mark processing_status as pending
        t1_db = db_session.query(models.Track).filter_by(video_id="v_mood1").first()
        t1_db.processing_status = "pending_classification"
        db_session.commit()

        # Run 2: Re-run create_mood_playlists
        create_mood_playlists(db_session)

        # v_mood1 is no longer eligible and must NOT be retained in Jazz Mix
        jazz_playlist_db = db_session.query(models.Playlist).filter_by(window_type="mood", window_label="Jazz").first()
        remaining_ids = {t.track_video_id for t in jazz_playlist_db.tracks}
        assert "v_mood1" not in remaining_ids
