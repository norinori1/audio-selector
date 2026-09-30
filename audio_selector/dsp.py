"""Basic SoundFile/NumPy observations. Diagnostics only: no FFT, no quality verdict."""
from pathlib import Path

import numpy as np
import soundfile as sf

FLOOR_DBFS = -120.0


def dbfs(value):
    return max(FLOOR_DBFS, 20 * float(np.log10(value))) if value > 0 else FLOOR_DBFS


def basic_dsp(path: Path):
    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    if audio.size == 0 or not np.isfinite(audio).all():
        raise ValueError(f"empty/nonfinite audio: {path.name}")
    return dict(duration_seconds=audio.shape[0] / rate, sample_rate=int(rate),
                channels=int(audio.shape[1]), peak_dbfs=dbfs(float(np.max(np.abs(audio)))),
                rms_dbfs=dbfs(float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))))
