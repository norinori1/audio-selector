"""Generate tiny original synthetic fixtures; no downloaded audio or production assets."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import chirp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("corpus/issue-2"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sr = 48000
    t = np.arange(sr * 3, dtype=np.float64) / sr
    rng = np.random.default_rng(20260930)
    beep = np.sin(2 * np.pi * 1000 * t) * ((t % .6) < .18)
    chime = sum(np.sin(2 * np.pi * f * t) * np.exp(-4 * np.maximum(t - start, 0))
                * (t >= start) for f, start in [(523.25, 0), (659.25, .3), (783.99, .6)])
    noise = rng.normal(0, .18, t.size)
    sounds = [
        ("01", "repeated high electronic beep / alert", .3 * beep),
        ("02", "ascending three-note bell-like confirmation chime", .25 * chime),
        ("03", "low rough buzzer", .3 * np.tanh(4 * np.sin(2 * np.pi * 110 * t))),
        ("04", "broadband noise / hiss", noise),
        ("05", "synthetic kick-like low decaying impacts", .6 * chirp(t % .75, 150, .75, 35)
         * np.exp(-12 * (t % .75))),
        ("06", "rising electronic sweep / whoosh proxy", .35 * chirp(t, 120, 3, 5000)
         * np.sin(np.pi * t / 3) ** 2),
        ("07", "steady low ambient tonal drone", .2 * np.sin(2 * np.pi * 65 * t)
         + .1 * np.sin(2 * np.pi * 97.5 * t)),
        ("08", "silence negative control", np.zeros(t.size)),
    ]
    manifest = []
    for identifier, description, samples in sounds:
        path = args.out / (identifier + ".wav")
        sf.write(path, np.clip(samples, -.95, .95), sr, subtype="PCM_16")
        manifest.append(dict(file=path.name, description=description, duration=3,
                             sample_rate=sr, channels=1,
                             sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                             source="original deterministic synthesis; no third-party samples"))
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
