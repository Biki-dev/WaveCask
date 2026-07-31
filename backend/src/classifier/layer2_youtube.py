"""
Layer 2 — YouTube Data API v3
"""

import os
import logging
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# YouTube Music category ID
MUSIC_CATEGORY_ID = "10"

# Category IDs that are clearly NOT music
NON_MUSIC_CATEGORY_IDS = {
    "1",   # Film & Animation
    "2",   # Autos & Vehicles
    "17",  # Sports
    "18",  # Short Movies
    "19",  # Travel & Events
    "20",  # Gaming
    "21",  # Videoblogging
    "22",  # People & Blogs
    "23",  # Comedy
    "24",  # Entertainment (ambiguous but not music)
    "25",  # News & Politics
    "26",  # Howto & Style
    "27",  # Education
    "28",  # Science & Technology
    "29",  # Nonprofits & Activism
}


def _get_youtube_client():
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise ValueError("YOUTUBE_API_KEY environment variable is not set")
    return build("youtube", "v3", developerKey=api_key)


def classify(video_id: str) -> tuple[bool | None, dict]:
    if not video_id:
        return None, {}

    try:
        youtube = _get_youtube_client()
        response = (
            youtube.videos()
            .list(
                part="snippet,topicDetails",
                id=video_id,
            )
            .execute()
        )

        items = response.get("items", [])
        if not items:
            logger.warning(f"L2: No YouTube data for video_id={video_id}")
            return None, {}

        snippet = items[0].get("snippet", {})
        topic_details = items[0].get("topicDetails", {})

        category_id = snippet.get("categoryId", "")
        topic_categories = topic_details.get("relevantTopicIds", [])

        # Check if any topic category is music-related
        music_topic = "/m/04rlf"  # Music (Freebase topic)
        is_music_topic = music_topic in topic_categories

        is_music: bool | None = None

        if category_id == MUSIC_CATEGORY_ID or is_music_topic:
            is_music = True
        elif category_id in NON_MUSIC_CATEGORY_IDS:
            is_music = False
      
        metadata = {
            "artist": snippet.get("channelTitle", "Unknown"),
            "song": snippet.get("title", "Unknown"),
            "genre": "Unknown",
            "release_year": str(snippet.get("publishedAt", "Unknown"))[:4],
        }

        logger.debug(f"L2 result for {video_id}: is_music={is_music}")
        return is_music, metadata

    except HttpError as e:
        logger.error(f"L2 YouTube API error for {video_id}: {e}")
        return None, {}
    except Exception as e:
        logger.error(f"L2 unexpected error for {video_id}: {e}")
        return None, {}
