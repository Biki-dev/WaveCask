"""
audio.py – Audio streaming endpoint.

Uses yt-dlp to resolve the best audio-only stream URL from YouTube for a
given video_id, then redirects the client directly to that URL.  The
redirect avoids having the server re-encode or buffer the full audio file.

A /api/audio/{video_id}/url endpoint is also provided for clients that
need the raw URL (e.g. the frontend audio element).
"""
import subprocess
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from src import models
from src.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


def _resolve_audio_url(video_id: str) -> str:
    """
    Use yt-dlp to resolve the best audio stream URL from YouTube.
    Returns the direct streaming URL (valid for ~6 hours).
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--format", "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best",
                "--get-url",
                "--no-playlist",
                "--quiet",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        stream_url = result.stdout.strip()
        if not stream_url:
            raise ValueError(f"yt-dlp returned empty URL for {video_id}: {result.stderr}")
        return stream_url
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="yt-dlp timed out resolving audio URL")
    except Exception as exc:
        logger.error("yt-dlp error for %s: %s", video_id, exc)
        raise HTTPException(status_code=502, detail=f"Failed to resolve audio stream: {exc}")


@router.get("/api/audio/{video_id}/url")
def get_audio_url(video_id: str, db: Session = Depends(get_db)):
    """
    Resolve and return the direct YouTube audio stream URL for a track.
    The frontend can feed this URL directly into an <audio> element.
    """
    track = db.query(models.Track).filter(models.Track.video_id == video_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    stream_url = _resolve_audio_url(video_id)
    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"

    return {
        "video_id": video_id,
        "stream_url": stream_url,
        "thumbnail_url": thumbnail_url,
        "title": track.raw_title,
        "artist": track.artist,
        "song": track.song,
        "duration_seconds": track.duration_seconds,
    }


@router.get("/api/audio/{video_id}/stream")
def stream_audio(video_id: str, db: Session = Depends(get_db)):
    """
    Redirect directly to the YouTube audio stream URL.
    """
    track = db.query(models.Track).filter(models.Track.video_id == video_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    stream_url = _resolve_audio_url(video_id)
    return RedirectResponse(url=stream_url, status_code=302)
