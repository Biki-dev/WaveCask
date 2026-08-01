import os
import json
import logging
import re
from typing import Optional, Tuple, Dict, Any, List

from pydantic import BaseModel, Field
from google import genai
from google.genai.types import GenerateContentConfig
from openai import OpenAI

logger = logging.getLogger(__name__)


class TrackMetadata(BaseModel):
    artist: str = Field(default="Unknown")
    song: str = Field(default="Unknown")
    genre: str = Field(default="Unknown")
    release_year: str = Field(default="Unknown")


def _clean_unknown(value: Any) -> str:
    text = str(value).strip() if value is not None else "Unknown"
    return "Unknown" if text.lower() in {"", "null", "none", "nan"} else text


def _normalize_metadata(data: Dict[str, Any]) -> Dict[str, str]:
    return {
        "artist": _clean_unknown(data.get("artist")),
        "song": _clean_unknown(data.get("song")),
        "genre": _clean_unknown(data.get("genre")),
        "release_year": _clean_unknown(data.get("release_year")),
    }


def _fallback_parse(raw_title: str, channel: str) -> Dict[str, str]:
    parts = []
    for delimiter in [" - ", " – ", " — ", " | "]:
        if delimiter in raw_title:
            parts = raw_title.split(delimiter)
            break

    artist = "Unknown"
    song = raw_title.strip()

    if len(parts) >= 2:
        artist = parts[0].strip()
        song = parts[1].strip()
    elif channel:
        artist = re.sub(r"(VEVO| - Topic|\s*Official\s*)$", "", channel, flags=re.IGNORECASE).strip()

    song = re.sub(
        r"\s*[(\[][^)\]]*(video|audio|lyrics|official|hq|hd|edit|remix|version|clip|visualizer)[^)\]]*[)\]]",
        "",
        song,
        flags=re.IGNORECASE,
    )
    song = re.sub(r"\s+", " ", song).strip()
    artist = re.sub(r"\s+", " ", artist).strip()

    return _normalize_metadata(
        {
            "artist": artist if artist else "Unknown",
            "song": song if song else raw_title,
            "genre": "Unknown",
            "release_year": "Unknown",
        }
    )


def _build_prompt(video_id: str, raw_title: str, channel: str) -> str:
    return (
        "You are an expert music metadata extraction tool.\n"
        "Return ONLY valid JSON matching the schema.\n\n"
        f"Video ID: {video_id}\n"
        f"Raw Title: {raw_title}\n"
        f"Channel/Uploader: {channel}\n\n"
        "Extract:\n"
        "artist: the actual original artist or band name.\n"
        "song: clean original song title.\n"
        "genre: a single main genre.\n"
        "release_year: the original release year.\n\n"
        "Use your knowledge of commercially released music.\n"
        "Infer the most likely primary genre.\n"
        "Infer the original release year.\n"
        "Only use 'Unknown' when absolutely impossible.\n"
        "Do not default to 'Unknown' simply because confidence is below 100%."
    )


def _gemini_enrich(video_id: str, raw_title: str, channel: str) -> Dict[str, str]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing.")

    client = genai.Client(api_key=api_key)
    prompt = _build_prompt(video_id, raw_title, channel)

    response = client.models.generate_content(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        contents=prompt,
        config=GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=TrackMetadata,
            temperature=0.1,
        ),
    )

    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        if isinstance(parsed, TrackMetadata):
            return _normalize_metadata(parsed.model_dump())
        if isinstance(parsed, dict):
            return _normalize_metadata(parsed)

    text = getattr(response, "text", "") or ""
    if text.strip():
        try:
            return _normalize_metadata(json.loads(text))
        except Exception:
            pass

    raise ValueError("Gemini returned no parseable structured output.")


def _openrouter_client() -> OpenAI:
    return OpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost"),
            "X-OpenRouter-Title": os.getenv("OPENROUTER_APP_TITLE", "wavecask-backend"),
        },
    )


def _openrouter_enrich(video_id: str, raw_title: str, channel: str) -> Dict[str, str]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is missing.")

    client = _openrouter_client()
    prompt = _build_prompt(video_id, raw_title, channel)

    response = client.chat.completions.create(
        model=os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash"),
        messages=[
            {
                "role": "system",
                "content": (
                    "You extract music metadata. Return only valid JSON with keys: "
                    "artist, song, genre, release_year."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )

    text = response.choices[0].message.content or ""
    if not text.strip():
        raise ValueError("OpenRouter returned empty content.")

    return _normalize_metadata(json.loads(text))


def enrich_track_metadata(
    video_id: str,
    raw_title: str,
    channel: str,
) -> Tuple[bool, Dict[str, str]]:
    """
    Provider order:
      1) Gemini
      2) OpenRouter
      3) heuristic fallback
    Override order with METADATA_PROVIDERS="openrouter,gemini,fallback"
    """
    providers = os.getenv("METADATA_PROVIDERS", "gemini,openrouter,fallback")
    order = [p.strip().lower() for p in providers.split(",") if p.strip()]

    for provider in order:
        try:
            if provider == "gemini":
                metadata = _gemini_enrich(video_id, raw_title, channel)
                logger.info(
                    "metadata_enrichment: resolved via Gemini for video_id=%s -> %s",
                    video_id,
                    metadata,
                )
                return True, metadata

            if provider == "openrouter":
                metadata = _openrouter_enrich(video_id, raw_title, channel)
                logger.info(
                    "metadata_enrichment: resolved via OpenRouter for video_id=%s -> %s",
                    video_id,
                    metadata,
                )
                return True, metadata

            if provider == "fallback":
                metadata = _fallback_parse(raw_title, channel)
                logger.info(
                    "metadata_enrichment: resolved via fallback for video_id=%s -> %s",
                    video_id,
                    metadata,
                )
                return True, metadata

        except Exception as e:
            logger.warning(
                "metadata_enrichment: provider=%s failed for video_id=%s: %s",
                provider,
                video_id,
                e,
            )

    return True, _fallback_parse(raw_title, channel)