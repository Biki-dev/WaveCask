"""
Layer 3 — Trained AudioCNN Model (.pth)
-----------------------------------------
Architecture matches the training notebook exactly:
  - Input:  log-mel spectrogram  [1, N_MELS=64, time]  float32
  - Model:  AudioCNN (4x Conv2d → AdaptiveAvgPool → Linear(256, 2))
  - Output: logits for 2 classes → argmax → label_to_idx lookup

Inference pipeline:
  1. Download YouTube audio via yt-dlp  (shared: audio_utils.download_audio)
  2. Load + resample to 16 kHz mono     (shared: audio_utils.audio_to_logmel)
  3. Compute log-mel spectrogram
  4. Run AudioCNN forward pass
  5. Delete temp audio file             (handled in finally block)
  6. Return (is_music: bool, "layer3")

Environment variables:
  MODEL_PATH  — absolute path to music_classifier.pth inside the container
                default: /app/models/music_classifier.pth

Returns (None, "") if:
  - MODEL_PATH not set or file missing
  - YouTube download fails
  - Any inference error
"""

import os
import logging
import shutil
import tempfile
from typing import Optional

from src.classifier.audio_utils import download_audio, audio_to_logmel, N_MELS

logger = logging.getLogger(__name__)

# label_to_idx = {"music": 0, "speech": 1}
MUSIC_CLASS_IDX = 0


def _build_audio_cnn():
    """Construct AudioCNN"""
    import torch.nn as nn

    class AudioCNN(nn.Module):
        def __init__(self, num_classes: int = 2):
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv2d(1, 32, kernel_size=3, padding=1),
                nn.BatchNorm2d(32),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(kernel_size=2),

                nn.Conv2d(32, 64, kernel_size=3, padding=1),
                nn.BatchNorm2d(64),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(kernel_size=2),

                nn.Conv2d(64, 128, kernel_size=3, padding=1),
                nn.BatchNorm2d(128),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(kernel_size=2),

                nn.Conv2d(128, 256, kernel_size=3, padding=1),
                nn.BatchNorm2d(256),
                nn.ReLU(inplace=True),
                nn.Dropout(0.25),
            )
            self.pool = nn.AdaptiveAvgPool2d((1, 1))
            self.classifier = nn.Sequential(
                nn.Flatten(),
                nn.Dropout(0.35),
                nn.Linear(256, num_classes),
            )

        def forward(self, x):
            x = self.features(x)
            x = self.pool(x)
            return self.classifier(x)

    return AudioCNN



def classify(
    video_id: str,
    raw_title: str,          # unused for audio inference, kept for API compat
    channel: str,            # unused for audio inference
    duration_seconds: Optional[float],  # unused for audio inference
) -> tuple[bool | None, str]:
    """
    Returns:
      (True,  "layer3")  — model says music
      (False, "layer3")  — model says not music
      (None,  "")        — model not available or inference failed
    """
    model_path = os.getenv("MODEL_PATH", "/app/models/music_classifier.pth")

    if not model_path or not os.path.exists(model_path):
        logger.warning(f"L3: MODEL_PATH='{model_path}' not found — skipping.")
        return None, ""

    audio_file: Optional[str] = None
    tmp_dir: Optional[str] = None

    try:
        import torch

        checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)

        if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
            AudioCNN = _build_audio_cnn()
            label_to_idx = checkpoint.get("label_to_idx", {"music": 1, "speech": 0})
            music_idx = label_to_idx.get("music", MUSIC_CLASS_IDX)

            model = AudioCNN(num_classes=len(label_to_idx))
            model.load_state_dict(checkpoint["model_state_dict"])
        else:
            logger.error("L3: Checkpoint format not recognised. Expected dict with 'model_state_dict'.")
            return None, ""

        model.eval()
        
        # Download 30 seconds of audio to a temporary directory (layer3 needs a representative snippet for CNN)
        tmp_dir = tempfile.mkdtemp(prefix="wavecask_l3_")
        audio_file = download_audio(video_id, tmp_dir, clip_seconds=30)

        if audio_file is None:
            logger.warning(f"L3: Could not download audio for {video_id} — skipping.")
            return None, ""

        # Convert audio to log-mel spectrogram
        logmel = audio_to_logmel(audio_file)
        x = torch.tensor(logmel, dtype=torch.float32).unsqueeze(0).unsqueeze(0)
        # shape: [1, 1, N_MELS, time]

        # Run inference
        with torch.no_grad():
            logits = model(x)              # [1, num_classes]
            pred_idx = int(logits.argmax(dim=1).item())

        is_music = (pred_idx == music_idx)
        logger.info(f"L3: video_id={video_id} pred_idx={pred_idx} → is_music={is_music}")
        return is_music, "layer3"

    except Exception as e:
        logger.error(f"L3: Inference error for {video_id}: {e}")
        return None, ""

    finally:
        # Cleanup temporary files
        if audio_file and os.path.exists(audio_file):
            try:
                os.remove(audio_file)
                logger.info(f"L3: Deleted temp audio: {audio_file}")
            except Exception:
                pass
        if tmp_dir and os.path.isdir(tmp_dir):
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass
