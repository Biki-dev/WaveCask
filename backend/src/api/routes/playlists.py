from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src import models, schemas
from src.database import get_db
from src.services.playlist_service import create_mix_playlist, get_playlist as get_playlist_record, list_playlists as list_playlist_records

router = APIRouter()


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
