"""Pinned retrieval contract constants, importable without loading torch/transformers."""
MODEL = "laion/clap-htsat-unfused"
REVISION = "8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a"
CONTRACT = dict(index_version="1.0", model=MODEL, revision=REVISION,
                preprocessing="mono-mean/librosa-soxr_hq/48k/10s-nonoverlap/zero-pad/v1",
                sample_rate=48000, segment_samples=480000, normalization="L2", dimension=512,
                transformers="4.44.2", librosa="0.10.2.post1", soundfile="0.12.1")
CONTRACT["text_preprocessing"] = "pinned-tokenizer/pad/truncate-77/v1"
