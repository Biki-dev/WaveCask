"""
Classification Pipeline
"""

import logging
from dataclasses import dataclass
from typing import Optional

from src.classifier import layer1_heuristics, layer2_youtube, layer3_model

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    is_music: bool = False
    classification_source: str = "unclassified"
    artist: str = "Unknown"
    song: str = "Unknown"
    genre: str = "Unknown"
    release_year: str = "Unknown"


def run_pipeline(
    video_id: str,
    raw_title: str,
    channel: str,
    duration_seconds: Optional[float],
) -> ClassificationResult:
    result = ClassificationResult()


    # Layer 1 — Heuristic Rule
    logger.info(f"Pipeline L1 → video_id={video_id}")
    is_music_l1, source_l1 = layer1_heuristics.classify(raw_title, channel)

    if is_music_l1 is True:
        result.is_music = True
        result.classification_source = source_l1
        logger.info(f"Pipeline resolved at L1: is_music=True")
        return result

    logger.info("L1 did not identify music. Proceeding to Layer 2.")


    # Layer 2 — YouTube Data API
    logger.info(f"Pipeline L2 → video_id={video_id}")
    is_music_l2, metadata = layer2_youtube.classify(video_id)

    if is_music_l2 is True:
        result.is_music = True
        result.classification_source = "layer2"
        result.artist = metadata.get("artist", "Unknown")
        result.song = metadata.get("song", "Unknown")
        result.genre = metadata.get("genre", "Unknown")
        result.release_year = metadata.get("release_year", "Unknown")
        logger.info(f"Pipeline resolved at L2: is_music=True")
        return result

    logger.info("L2 did not identify music. Proceeding to Layer 3.")


    # Layer 3 — Trained Audio Model
    logger.info(f"Pipeline L3 → video_id={video_id}")
    is_music_l3, source_l3 = layer3_model.classify(video_id, raw_title, channel, duration_seconds)

    if is_music_l3 is True:
        result.is_music = True
        result.classification_source = source_l3 if source_l3 else "layer3"
        logger.info(f"Pipeline resolved at L3: is_music=True")
        return result
    else:
        result.is_music = False
        result.classification_source = "layer3"
        logger.info("Pipeline resolved at L3: is_music=False")
        return result
