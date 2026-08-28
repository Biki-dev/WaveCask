"""Service layer for the WaveCask backend.

The code in this package keeps workflow orchestration separate from the FastAPI
routes so that endpoint code stays thin and easy to navigate.
"""

from .playlist_service import (
    create_context_playlists,
    create_mix_playlist,
    create_mood_playlists,
    get_playlist,
    list_playlists,
)
from .track_service import (
    classify_pending_tracks,
    embed_classified_tracks,
    enrich_completed_tracks,
    enrich_single_track,
    refresh_implicit_track_scores,
    upsert_track_from_event,
)
from .playlist_mix import build_mix_rows, window_label_from_request
from .playlist_context import build_all_time_rows, build_commute_rows, build_late_night_rows
from .playlist_mood import (
    cluster_genres,
    cosine_similarity,
    load_existing_mood_playlists,
    load_existing_playlist_rows,
    load_playlist_session_counts,
    merge_playlist_rows,
    parse_audio_embedding,
    parse_release_year,
    playlist_profile,
    score_playlist_match,
    track_recency_weight,
)

__all__ = [
    "classify_pending_tracks",
    "embed_classified_tracks",
    "enrich_completed_tracks",
    "enrich_single_track",
    "refresh_implicit_track_scores",
    "upsert_track_from_event",
    "create_context_playlists",
    "create_mix_playlist",
    "create_mood_playlists",
    "get_playlist",
    "list_playlists",
    "build_mix_rows",
    "window_label_from_request",
    "build_late_night_rows",
    "build_commute_rows",
    "build_all_time_rows",
    "parse_audio_embedding",
    "cosine_similarity",
    "track_recency_weight",
    "parse_release_year",
    "load_playlist_session_counts",
    "playlist_profile",
    "load_existing_mood_playlists",
    "score_playlist_match",
    "load_existing_playlist_rows",
    "merge_playlist_rows",
    "cluster_genres",
]
