#!/usr/bin/env python3
"""Measure deterministic expiry correctness and optional local model timings.

Never opens a camera or downloads data. An optional image is read from disk and
used only in memory. Run with the project's Python environment from any folder.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from events import Journey, MAX_SAMPLE_GAP, VISIT_GAP
from geometry import ShelfConfig, observe


def summary_ms(values):
    ordered = sorted(values)
    return {
        "samples": len(ordered), "median_ms": round(statistics.median(ordered), 4),
        "p95_ms": round(ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)], 4),
        "max_ms": round(max(ordered), 4),
    }


def qualified_journey():
    journey = Journey(ShelfConfig())
    result = {"faces": [{"bbox": [100, 100, 100, 160]}]}
    for now in (0.0, 0.75, 1.5):
        state = journey.process({"zone": "left"}, result, now)
    assert state["offer"]["zone"] == "left"
    return journey


def expiry_benchmark():
    cases = 1000
    stale = 0
    durations = []
    for step in range(1, cases + 1):
        gap = MAX_SAMPLE_GAP + (VISIT_GAP - MAX_SAMPLE_GAP) * step / cases
        journey = qualified_journey()
        started = perf_counter()
        state = journey.snapshot(1.5 + gap)
        durations.append((perf_counter() - started) * 1000)
        assert state["current_zone"] is None and state["dwell_s"] == 0
        stale += state["offer"]["zone"] is not None
    return {"cases": cases, "gap_range_s": [1.501, 2.5],
            "stale_zone_offers": stale, "snapshot_time": summary_ms(durations)}


def geometry_benchmark(iterations=10000):
    config = ShelfConfig()
    result = {"width": 640, "height": 480,
              "faces": [{"usable": True, "gaze": [0, 0, 1],
                         "eye_centres": [[300, 240], [340, 240]]}]}
    for _ in range(100):
        observe(result, config)
    started = perf_counter()
    for _ in range(iterations):
        observation = observe(result, config)
    elapsed = perf_counter() - started
    assert observation["zone"] == "centre"
    return {"iterations": iterations, "mean_ms": round(elapsed * 1000 / iterations, 6)}


def inference_benchmark(model_dir, image_path, samples, warmup):
    import cv2
    import numpy as np
    import openvino as ov
    from vision import EYE_MODEL, VisionPipeline

    started = perf_counter()
    pipeline = VisionPipeline(model_dir)
    compile_ms = (perf_counter() - started) * 1000
    stage_times = defaultdict(list)
    models = {**pipeline._models, EYE_MODEL: pipeline._eye_model}
    # Instrument the actual model calls only for this benchmark. Include runtime
    # inference and copied output arrays; image preprocessing stays in total time.
    for name, model in models.items():
        original = model.run

        def timed(inputs, original=original, name=name):
            started = perf_counter()
            output = original(inputs)
            stage_times[name].append((perf_counter() - started) * 1000)
            return output

        model.run = timed

    inputs = {"blank_640x480": np.zeros((480, 640, 3), dtype=np.uint8)}
    provenance = None
    if image_path:
        content = image_path.read_bytes()
        frame = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("The supplied image could not be decoded.")
        inputs["provided_image"] = frame
        provenance = {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
                      "shape": list(frame.shape)}
    scenarios = {}
    for name, frame in inputs.items():
        for _ in range(warmup):
            pipeline.infer(frame)
        stage_times.clear()
        totals = []
        quality = Counter()
        face_counts = Counter()
        for _ in range(samples):
            started = perf_counter()
            result = pipeline.infer(frame)
            totals.append((perf_counter() - started) * 1000)
            json.dumps(result, allow_nan=False)
            face_counts[len(result["faces"])] += 1
            quality.update(face["quality_reason"] for face in result["faces"])
        scenarios[name] = {
            "pipeline": summary_ms(totals), "face_counts": dict(face_counts),
            "quality_counts": dict(quality),
            "model_calls": {key: summary_ms(value) for key, value in stage_times.items()},
        }
    return {"openvino": ov.__version__, "opencv": cv2.__version__,
            "numpy": np.__version__, "device": "CPU", "inference_threads": 2,
            "performance_hint": "LATENCY", "compile_ms": round(compile_ms, 2),
            "warmup_per_scenario": warmup, "image": provenance, "scenarios": scenarios}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", action="store_true", help="Also run real OpenVINO models.")
    parser.add_argument("--model-dir", type=Path, default=ROOT / "models")
    parser.add_argument("--image", type=Path, help="Optional existing image for model timing.")
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.samples < 1 or args.warmup < 0:
        parser.error("samples must be positive and warmup must be non-negative")
    if args.image and not args.models:
        parser.error("--image requires --models")
    report = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "system": platform.system(),
        "machine": platform.machine(), "expiry": expiry_benchmark(),
        "geometry": geometry_benchmark(),
        "limits": "Synthetic timing and publisher-image inference only; no camera, transport, browser or physical gaze accuracy test.",
    }
    if args.models:
        report["inference"] = inference_benchmark(args.model_dir, args.image, args.samples, args.warmup)
    rendered = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
