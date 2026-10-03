# Debugging report

Reviewed on 3 October 2026 against baseline `fb25455`. The scope is the local Python service and plain JavaScript client. Tests use synthetic JPEGs and small fake pipelines so that timing and failure paths can be controlled. Browser evidence belongs in [the audit](AUDIT.md).

## Reproduction and hypotheses

The original four server tests passed. Five additional regression tests, written before the server changes, then failed: the run reported five failures and four passes.

| Rank | Hypothesis | Reproduction and evidence | Finding |
| --- | --- | --- | --- |
| 1 | Cancelling the request releases admission before native inference finishes. | Block a fake pipeline with a thread event, cancel its HTTP task, then send a second frame before releasing the first. The second request entered inference and eventually returned 503, instead of the expected immediate 429. | Confirmed. Cancelling `asyncio.to_thread`'s await does not stop the running thread, but the request's `async with` released its lock. |
| 2 | Failure handling bypasses the generation check. | Block a failing pipeline, reset the run, release the failure. The old frame returned 503 instead of 409. | Confirmed. The exception path called `journey.stop()` before checking whether the run had changed. |
| 3 | Input checks happen too late or omit a resource bound. | Post 20,002 bytes of whitespace and `{}` as setup JSON; spy on decoding a 1,921-pixel-wide JPEG; make the native decoder raise `cv2.error`. Results were 200, a decoder call before size rejection, and 500 respectively. | Confirmed. Setup parsing had no application size limit, dimensions were checked after decode, and decoder errors were outside the recovery boundary. |

These are deterministic software reproductions. They do not measure physical gaze accuracy, shopper behaviour or camera hardware reliability.

## Corrections

The inference lock now remains occupied until the native worker finishes, including when the HTTP task is cancelled or its inference deadline expires. A competing request receives 429. The worker result is consumed and discarded; completion cannot update a cancelled request's visit. The server waits for outstanding native work before releasing its pipeline during normal shutdown.

Stop, Reset and successful setup changes increment a generation. Both inference success and failure check that generation before changing visit state. Response headers also carry a service instance and generation pair. The browser captures the pair before JPEG encoding and sends it with the frame. This catches a frame that first reaches the server after a control change. A new service instance lets the browser recover when the server restarts. See [the error-handling contract](ERROR_HANDLING.md) for the exact headers and legacy-client limit.

Uploads have a five-second deadline. JPEG bodies are limited to 2,000,000 bytes; setup JSON is limited to 16,384 bytes. JPEG frame dimensions are checked in the encoded header before OpenCV decoding, and must be between 120 and 1,920 pixels per side. A native decoder rejection returns 422. Frames whose upload and processing exceed the 1.5-second sample gap are discarded with 409 and cannot become current observations.

Model execution, result validation and visit processing share a recovery boundary. A failure ends the affected visit and returns 503. Startup failures and request failures expose an actionable message and a request ID, while server diagnostics contain the exception class and stack locations. Neither response bodies nor those diagnostics echo raw exception messages or camera data.

## Regression evidence

Run from the repository root:

```sh
.venv/bin/python -m pytest tests/test_server.py -q
.venv/bin/python -m compileall -q server.py api_support.py
git diff --check
```

The focused server suite passed 36 cases after the corrections. Compilation and whitespace checks passed. Pytest reported one Starlette deprecation warning about its `httpx` TestClient integration; it did not fail a test.

The tests cover malformed frames, declared and actual byte limits, invalid setup, origin rejection, safe diagnostics, cancellation, upload and inference deadlines, control changes during inference, delayed frames, service restarts and fresh-frame recovery. Frontend response-order tests are maintained separately with the client tests.

## Limits and follow-up

The final browser review reproduced the original generic setup error in a separate baseline process and the corrected field-specific error in the current app. Correcting camera height from 2 m to 0.3 m then saved successfully. [Before recording](videos/before-setup-validation.mp4), [after recording](videos/after-setup-validation.mp4) and [all screenshots](AUDIT.md#saved-screenshots) preserve that evidence without opening a camera.

Independent review also found two client lifecycle defects: stale displayed geometry after a service restart, and frame callbacks surviving `pagehide`. Both are fixed and independently rechecked. The final integrated suites pass 68 Python and 19 JavaScript cases. A physical camera test is still separate.

- The frame-age clock starts when the inference handler admits the request. Time before server arrival is not measured.
- A Python timeout cannot terminate an already running native model call. Admission stays closed until it returns; a permanently stuck native call requires process intervention and can delay shutdown.
- The API keeps a compatibility path for clients that omit both session headers. Those clients receive the in-flight generation check, but cannot identify a frame that first arrives after a control change.
- Model installation, live camera use and browser screenshots are separate checks. This report does not claim that fake-pipeline tests establish those outcomes.
