# Performance and correctness review

Review date: 3 October 2026. Scope: local Python inference, shelf geometry and temporary visit state. Measurements use synthetic observations and one publisher sample image. No camera is opened.

## Decision recorded before implementation

The highest-priority bounded defect is stale offer expiry. `Journey.expire()` clears dwell when the last sample is more than 1.5 seconds old, but only resets the offer after the 2.5-second visit timeout. A display poll in that interval can receive an old zone offer while `current_zone` is null and `dwell_s` is zero. The offer-hold timer should limit switching between valid observations; it should not preserve an offer after its evidence expires.

The proposed change calls `general()` alongside `clear_dwell()` at the existing sample timeout. It preserves the visit grace period, cumulative totals, event history, normal offer holding and response shape. Resumed observations must earn the dwell threshold again. This is a state-invariant repair, with no new model, smoothing, dependency or threshold.

The benchmark will sweep 1,000 independent snapshots, at gaps from 1.501 to 2.500 seconds after a qualified sample. Its correctness metric is the number of stale zone offers returned. Separate native inference timing will identify the expensive stages; it does not establish webcam performance or physical shelf accuracy.

## Three priority risks

| Priority | Evidence and consequence | Action and acceptance |
| --- | --- | --- |
| 1. Stale offer outlives sample validity | At baseline `fb25455`, every one of 1,000 snapshots in the sample-expired/visit-retained interval returned the old offer. Resuming a frame in that interval also retained the offer before fresh dwell qualified. | Implemented the expiry repair. The same sweep must return zero zone offers; reacquisition must earn dwell again. |
| 2. Uncalibrated geometry is treated as a precise point by the maths | `geometry.observe()` uses one operator distance, a guessed horizontal field of view, a centred principal point, square pixels and a level camera in the shelf plane. Its 5 cm maximum boundary margin is a heuristic. No labelled physical shelf data exists in this review. | Keep the mapping explicitly approximate. Before changing thresholds or claiming accuracy, measure false zone assignments, abstentions and transition delay on a labelled shelf protocol. Hardware calibration and depth estimation are medium efforts described in [RESEARCH.md](RESEARCH.md). |
| 3. Inference time is only part of frame age | Models run synchronously, with a lock and a two-thread CPU limit. Work scales with accepted face count, up to four faces. Browser capture, JPEG encoding, HTTP handling and display polling add delay beyond the reported inference time. | Profile each stage before changing concurrency. Keep one active inference worker and reject stale work. Measure request age and visible update age on target hardware before promising latency. A model timer alone cannot establish this. |

Priority 1 was selected because it is a reproduced correctness failure with a small, testable fix. Priority 2 has greater uncertainty about real-world accuracy, but cannot be resolved by a code-only benchmark. Priority 3 did not reveal a native-inference bottleneck on this machine.

The accompanying API changes address another part of priority 3: a frame whose upload/inference takes over 1.5 seconds from server request start is rejected as `409/frame_expired`. This bounds time spent inside that request. Capture-to-arrival age is still unknown because the protocol has no client timestamp and clock contract. See [ERROR_HANDLING.md](ERROR_HANDLING.md) for request and cancellation behaviour.

## Before and after

The baseline used `events.py`, `geometry.py` and `vision.py` from `fb25455`. The final run differs in these modules only by the expiry repair. Runs began at 10:56:01 and 10:56:37 UTC on 3 October 2026. Both used the same benchmark script and inputs.

| Measurement | Before | After | Interpretation |
| --- | ---: | ---: | --- |
| Stale zone offers returned, 1,000 independent snapshots | 1,000 | 0 | The reproduced stale-offer error is eliminated in the tested interval. |
| Snapshot median, ms | 0.0016 | 0.0017 | No meaningful speed claim at this resolution. |
| Snapshot p95, ms | 0.0020 | 0.0019 | Timing noise is larger than any useful conclusion. |
| `observe()` mean over 10,000 calls, ms | 0.001285 | 0.001300 | Geometry is negligible in this benchmark. |
| Blank-frame pipeline median / p95, ms | 4.6383 / 4.8228 | 4.6217 / 4.8028 | Face detection only. |
| Publisher-image pipeline median / p95, ms | 6.9938 / 7.3713 | 6.9419 / 7.2137 | All five models execute; one accepted face on every repetition. |
| Publisher-image pipeline maximum, ms | 7.5693 | 7.5572 | Maximum among 100 repeated runs, not a worst-case guarantee. |
| Model load and compilation, ms | 190.92 | 186.78 | Measured separately from warmed inference. |

This is a correctness improvement. There was no model or geometry optimisation, and the small timing differences do not establish a speedup.

The threshold sweep creates a fresh journey for each snapshot. Three left-zone observations at 0, 0.75 and 1.5 seconds qualify an offer. The next snapshot occurs at a gap of `1.5 + n / 1000` seconds after the last observation, for `n=1..1000`. Each snapshot must have no current zone, zero dwell and a general offer. This covers the whole sampled interval from 1.501 to 2.500 seconds without a later frame hiding the problem.

The change is covered by nine expiry cases across all three zones and three gaps, an exact-threshold case and a resumed-frame case without an intervening display poll. Ten cases failed before the fix; all eleven pass afterwards. Together with the existing geometry and journey tests, the focused run reports **32 passed**. Existing tests still cover offer holding during a valid zone change, multiple faces, uncertain samples, position jumps and visit expiry.

Expiry is evaluated when the server processes a frame or a state read. A customer display that polls every 500 ms sees the corrected state on its next successful poll. Browser scheduling, transport and connection loss can add delay, so this is not a promise that the screen changes at exactly 1.5 seconds.

## Native inference profile

Host: Apple M4 Max, Darwin arm64, Python 3.12.14. Runtime: OpenVINO `2026.4.1-22982-e213a147257-releases/2026/4`, OpenCV `5.0.0`, NumPy `2.5.3`. Each compiled model uses `CPU`, `LATENCY` and two inference threads. Model size and SHA-384 verification passed for all nine files, totalling 18,685,381 bytes.

Each scenario received 10 warm-up calls and 100 measured calls. Total timing wraps `VisionPipeline.infer()` with `perf_counter`; stage timing wraps each model's `run()` and includes runtime inference and output copying. Preprocessing, face filtering and quality checks are included in total timing. JSON finiteness is checked outside the timer. The p95 uses the nearest-rank definition. These stage timers are installed only in the benchmark and do not alter production code.

| Model stage on the publisher image | Calls in 100 frames | Baseline median per call, ms | Baseline p95 per call, ms |
| --- | ---: | ---: | ---: |
| Face detector | 100 | 3.9041 | 4.0421 |
| Head pose | 100 | 0.4968 | 0.5662 |
| Facial landmarks | 100 | 0.8216 | 0.9235 |
| Eye state | 200 | 0.0772 | 0.1368 |
| Gaze direction | 100 | 0.6744 | 0.7551 |

The face detector is the largest measured stage. Native total p95 is well below the browser's 333 ms target sampling interval on this input. Running every model asynchronously would complicate ordering and stale-result handling without evidence that this prototype needs the throughput. OpenVINO recommends its latency hint for synchronous single-request inference and distinguishes that use from throughput-oriented asynchronous work. [OpenVINO performance hints](https://docs.openvino.ai/2026/openvino-workflow/running-inference/optimize-inference/high-level-performance-hints.html)

The sample is Intel's [published gaze illustration](https://raw.githubusercontent.com/openvinotoolkit/open_model_zoo/a6946b6d6ce42cbf4278df20275fab199655fc7d/models/intel/gaze-estimation-adas-0002/assets/ill_for_gaze.png), not a captured shopper frame. Its PNG signature and decoded shape were checked. Size: 145,802 bytes; dimensions: 301 by 334 pixels; SHA-256: `1a146a14a807ff08f6ded73d32b7e4efc3a8df3d89f04c001af5e90fa65f5a25`. It returned one `ok` face on each measured repetition. Repeating one image checks execution stability and timings; it is not a detection or gaze accuracy dataset. The image and raw camera data are not included in the repository.

## Reproduce

From the repository root, with dependencies installed:

```sh
.venv/bin/python -m pytest -q tests/test_events.py tests/test_geometry.py
.venv/bin/python scripts/benchmark_pipeline.py
.venv/bin/python scripts/download_models.py --verify-only
.venv/bin/python scripts/benchmark_pipeline.py --models --image /path/to/ill_for_gaze.png --output /tmp/trace-benchmark.json
```

The default benchmark needs no models or images. `--models` also runs generated blank frames; `--image` adds an existing local image. It never opens a camera or downloads inputs. To reproduce the baseline, copy this benchmark script into `scripts/` in a separate checkout of `fb25455`, use the same Python environment and verified model directory through `--model-dir`, and supply the identical image. Keep the normal working checkout intact.

The benchmark script SHA-256 for both recorded runs is `f982e2941b7760c5c48ec5512376ff25e26cd41e9db0d6fa050c01ef7f46c093`. The final `events.py` SHA-256 is `c7bcfbc9f05f6a6b9a1d108bb2d3443f70ad2b608af3c832e75801b4334881a1`. Hardware load and runtime changes will affect timing; the deterministic stale-offer count should remain zero.

No browser latency, webcam timing, sustained load, multi-face timing, memory growth or physical gaze accuracy measurement is claimed here. The existing manifest records a separate earlier video smoke check; its figures are not presented as fresh measurements from this review.
