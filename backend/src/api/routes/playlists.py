"""
playlists.py – FastAPI routes for playlist operations including the
               WaveCask recommendation engine endpoints.
"""
from datetime import datetime, timezone

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src import models, schemas
from src.database import get_db
from src.jobs_recommendation import fit_track_clusters, rebuild_session_features
from src.repositories.recommendation_repository import (
    rebuild_engagement,
    rebuild_taste_profile,
)
from src.services.playlist_recommendation import build_playlist, persist_recommendation
from src.services.playlist_service import (
    create_mix_playlist,
    get_playlist as get_playlist_record,
    list_playlists as list_playlist_records,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Existing playlist endpoints (unchanged contract)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/playlists", response_model=list[schemas.PlaylistSummaryResponse])
def list_playlists(db: Session = Depends(get_db)):
    return list_playlist_records(db)


@router.get("/api/playlists/{playlist_id}", response_model=schemas.PlaylistResponse)
def get_playlist(playlist_id: int, db: Session = Depends(get_db)):
    playlist = get_playlist_record(db, playlist_id)
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return playlist


@router.post("/api/playlists/mix", response_model=schemas.PlaylistResponse, status_code=201)
def create_mix_playlist_endpoint(payload: schemas.PlaylistMixCreate, db: Session = Depends(get_db)):
    playlist, _rows = create_mix_playlist(
        db,
        name=payload.name,
        window_type=payload.window_type,
        limit=payload.limit,
        play_weight=payload.play_weight,
        implicit_weight=payload.implicit_weight,
        day_of_week=payload.day_of_week,
        month=payload.month,
        year=payload.year,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    if not playlist:
        raise HTTPException(status_code=404, detail="No tracks matched the requested mix window")
    return playlist


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation engine endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/api/playlists/discover-weekly",
    response_model=schemas.PlaylistResponse,
    status_code=201,
)
def discover_weekly(
    payload: schemas.RecommendationRequest, db: Session = Depends(get_db)
):
    """
    Generate or refresh the Discover Weekly playlist from the global taste profile.
    The playlist is keyed to the current ISO week so it refreshes automatically each
    Monday in the nightly job; calling this endpoint regenerates it on demand.
    """
    profile = db.query(models.TasteProfile).filter_by(profile_key="global").first()
    if profile is None:
        raise HTTPException(
            status_code=409,
            detail="Taste profile is not ready. Run /api/playlists/recommendation-models/refresh first.",
        )

    week_key = datetime.now(timezone.utc).strftime("%G-W%V")
    rows = build_playlist(
        db,
        algorithm="discover_weekly",
        profile_vector=profile.embedding,
        limit=payload.limit,
        generated_for=week_key,
    )
    playlist = persist_recommendation(
        db,
        name="Discover Weekly",
        algorithm="discover_weekly",
        model_version="v1",
        generated_for=week_key,
        rows=rows,
    )
    if playlist is None:
        raise HTTPException(status_code=404, detail="No eligible tracks for Discover Weekly")
    return playlist


@router.post(
    "/api/playlists/radio",
    response_model=schemas.PlaylistResponse,
    status_code=201,
)
def song_radio(payload: schemas.RadioRequest, db: Session = Depends(get_db)):
    """
    Generate a radio playlist seeded from a single track's audio embedding.
    Returns 30 tracks (configurable) that are sonically and contextually similar
    to the seed, excluding the seed itself via the repetition penalty.
    """
    seed = (
        db.query(models.Track)
        .filter(
            models.Track.video_id == payload.seed_video_id,
            models.Track.audio_embedding.isnot(None),
        )
        .first()
    )
    if seed is None:
        raise HTTPException(
            status_code=404, detail="Seed track not found or has no embedding"
        )

    rows = build_playlist(
        db,
        algorithm="song_radio",
        profile_vector=seed.audio_embedding,
        seed_ids=[seed.video_id],
        limit=payload.limit,
    )
    playlist = persist_recommendation(
        db,
        name=f"Radio: {seed.song}",
        algorithm="song_radio",
        model_version="v1",
        generated_for=f"seed:{seed.video_id}",
        rows=rows,
    )
    if playlist is None:
        raise HTTPException(status_code=404, detail="No similar tracks found")
    return playlist


@router.post(
    "/api/playlists/also-liked",
    response_model=schemas.PlaylistResponse,
    status_code=201,
)
def also_liked(payload: schemas.AlsoLikedRequest, db: Session = Depends(get_db)):
    """
    Generate a 'Listeners Also Liked' playlist from one or more seed tracks.
    Candidates are ranked primarily by co-occurrence lift, then by the mean
    embedding centroid of the seed set.
    """
    if not payload.seed_video_ids:
        raise HTTPException(status_code=422, detail="At least one seed track is required")

    # Deduplicate and cap at 20 seeds
    seed_ids = list(dict.fromkeys(payload.seed_video_ids))[:20]

    seed_vectors = (
        db.query(models.Track.audio_embedding)
        .filter(
            models.Track.video_id.in_(seed_ids),
            models.Track.audio_embedding.isnot(None),
        )
        .all()
    )
    if not seed_vectors:
        raise HTTPException(status_code=404, detail="No embedded seed tracks found")

    centroid = np.mean(
        np.asarray([v[0] for v in seed_vectors], dtype=np.float32), axis=0
    )
    centroid = centroid / (np.linalg.norm(centroid) + 1e-8)

    rows = build_playlist(
        db,
        algorithm="also_liked",
        profile_vector=centroid.tolist(),
        seed_ids=seed_ids,
        limit=payload.limit,
    )
    playlist = persist_recommendation(
        db,
        name="Listeners Also Liked",
        algorithm="also_liked",
        model_version="v1",
        generated_for=":".join(sorted(seed_ids)),
        rows=rows,
    )
    if playlist is None:
        raise HTTPException(status_code=404, detail="No related tracks found")
    return playlist


@router.post(
    "/api/playlists/recommendation-models/refresh",
    response_model=schemas.RecommendationTrainResponse,
)
def refresh_recommendation_models(db: Session = Depends(get_db)):
    """
    Rebuild all recommendation model artifacts:
      1. Track engagement features (SQL window functions over raw_events)
      2. MiniBatchKMeans cluster assignments
      3. Session co-occurrence pairs
      4. Global taste profile

    This runs synchronously in the request worker – it is intended only for
    development or administrative use.  In production the nightly scheduler
    is the normal execution path.  Protect this endpoint behind auth or a
    firewall in public deployments.
    """
    engagement_tracks    = rebuild_engagement(db)
    clusters_version     = fit_track_clusters(db)
    cooccurrence_pairs   = rebuild_session_features(db)
    taste_profile_tracks = rebuild_taste_profile(db)

    return schemas.RecommendationTrainResponse(
        clusters_version=clusters_version,
        engagement_tracks=engagement_tracks,
        cooccurrence_pairs=cooccurrence_pairs,
        taste_profile_tracks=taste_profile_tracks,
    )
