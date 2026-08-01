import json
import logging
import os
import shutil
import tempfile
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

from src.classifier.audio_utils import download_audio, CLIP_SECONDS

logger = logging.getLogger(__name__)

# OpenL3 settings
CONTENT_TYPE    = "music"   # matches the music-focused model weights
EMBEDDING_SIZE  = 512       # 512 or 6144; we want the compact 512-dim variant
INPUT_REPR      = "mel256"  # OpenL3 default; mel128 is also available
HOP_SIZE        = 0.5       # seconds between consecutive embedding frames


def _openl3_embed(audio_path: str) -> np.ndarray:
    import openl3
    import soundfile as sf

    audio, sr = sf.read(audio_path, always_2d=False)
    # OpenL3 expects mono; average channels if stereo
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    # emb shape: (num_frames, embedding_size)
    emb, _ = openl3.get_audio_embedding(
        audio,
        sr,
        content_type=CONTENT_TYPE,
        embedding_size=EMBEDDING_SIZE,
        input_repr=INPUT_REPR,
        hop_size=HOP_SIZE,
        verbose=False,
    )
    # Mean-pool across time → (512,)
    vector = emb.mean(axis=0).astype(np.float32)
    logger.info(
        f"audio_embedding: OpenL3 returned {emb.shape[0]} frames → "
        f"pooled to shape {vector.shape}"
    )
    return vector


def _vector_to_pgvector(vec: np.ndarray) -> str:
    """Convert a 1-D numpy array to the pgvector literal format: '[0.1, 0.2, ...]'"""
    return "[" + ",".join(f"{v:.8f}" for v in vec.tolist()) + "]"


def extract_and_store_embedding(video_id: str, db: Session) -> bool:
    tmp_dir:    Optional[str] = None
    audio_file: Optional[str] = None

    try:
        tmp_dir    = tempfile.mkdtemp(prefix="wavecask_emb_")
        audio_file = download_audio(
            video_id=video_id,
            out_dir=tmp_dir,
            clip_seconds=CLIP_SECONDS,
        )

        if audio_file is None or not os.path.exists(audio_file):
            raise RuntimeError(f"Audio download returned nothing for {video_id}")

       
        vector = _openl3_embed(audio_file)                   # (512,) float32

        if vector.shape != (EMBEDDING_SIZE,):
            raise ValueError(
                f"Unexpected embedding shape {vector.shape} "
                f"(expected ({EMBEDDING_SIZE},))"
            )


        pgvec_str = _vector_to_pgvector(vector)

        db.execute(
            text("""
                UPDATE tracks
                   SET audio_embedding    = CAST(:emb AS vector),
                       processing_status  = 'embedding_done',
                       updated_at         = NOW()
                 WHERE video_id = :vid
            """),
            {"emb": pgvec_str, "vid": video_id},
        )
        db.commit()
        logger.info(
            f"audio_embedding: Stored 512-dim embedding for video_id={video_id}"
        )
        return True

    except Exception as exc:
        logger.error(
            f"audio_embedding: Failed for video_id={video_id}: {exc}",
            exc_info=True,
        )
        try:
            db.rollback()
            db.execute(
                text("""
                    UPDATE tracks
                       SET processing_status = 'failed',
                           updated_at        = NOW()
                     WHERE video_id = :vid
                """),
                {"vid": video_id},
            )
            db.commit()
        except Exception as db_exc:
            logger.error(
                f"audio_embedding: Also failed to set 'failed' status "
                f"for {video_id}: {db_exc}"
            )
        return False

    finally:
    
        if audio_file and os.path.exists(audio_file):
            try:
                os.remove(audio_file)
                logger.debug(f"audio_embedding: Deleted temp WAV {audio_file}")
            except Exception:
                pass
        if tmp_dir and os.path.isdir(tmp_dir):
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass
