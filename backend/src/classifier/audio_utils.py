import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Shared audio config (kept in sync with training notebook)
TARGET_SR  = 16_000
N_MELS     = 64
N_FFT      = 1024
HOP_LENGTH = 320
FMIN       = 20
FMAX       = 8_000
EPS        = 1e-6

# How many seconds to download for embedding (5 s is enough, saves bandwidth)
CLIP_SECONDS = 5


def download_audio(
    video_id: str,
    out_dir: str,
    clip_seconds: Optional[int] = None,
) -> Optional[str]:
    try:
        import yt_dlp

        url          = f"https://www.youtube.com/watch?v={video_id}"
        out_template = os.path.join(out_dir, f"{video_id}.%(ext)s")
        out_wav      = os.path.join(out_dir, f"{video_id}.wav")

        ydl_opts: dict = {
            "format":      "bestaudio/best",
            "outtmpl":     out_template,
            "quiet":       True,
            "no_warnings": True,
            "postprocessors": [{
                "key":              "FFmpegExtractAudio",
                "preferredcodec":   "wav",
                "preferredquality": "192",
            }],
            "noplaylist": True,
        }

        # If clip_seconds is specified, we can use yt-dlp's built-in download_ranges
        if clip_seconds is not None:
            ydl_opts["download_ranges"] = lambda info_dict, ydl: [{
                'start_time': 0,
                'end_time': clip_seconds,
            }]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)

        if os.path.exists(out_wav):
            logger.info(f"audio_utils: Downloaded audio → {out_wav}")
            return out_wav

        logger.warning(f"audio_utils: yt-dlp finished but WAV not found for {video_id}")
        return None

    except Exception as exc:
        logger.error(f"audio_utils: Download failed for {video_id}: {exc}")
        return None


def audio_to_logmel(file_path: str, duration: Optional[float] = None):
    """
    Load a WAV (or any librosa-supported format) and return a normalised
    log-mel spectrogram as float32 ndarray of shape [N_MELS, time_frames].
    """
    import librosa
    import numpy as np

    audio, _ = librosa.load(file_path, sr=TARGET_SR, mono=True, duration=duration)
    if audio is None or len(audio) == 0:
        raise ValueError(f"audio_utils: Empty audio from {file_path}")

    mel = librosa.feature.melspectrogram(
        y=audio,
        sr=TARGET_SR,
        n_fft=N_FFT,
        hop_length=HOP_LENGTH,
        n_mels=N_MELS,
        fmin=FMIN,
        fmax=FMAX,
        power=2.0,
    )
    logmel = librosa.power_to_db(mel, ref=np.max)
    logmel = (logmel - logmel.mean()) / (logmel.std() + EPS)
    return logmel.astype(np.float32)

