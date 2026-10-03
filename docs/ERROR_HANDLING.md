# Error handling

The service runs locally with one shared camera journey and one admitted inference request. It has no remote runtime service, database or payment operation. Network retry chains, circuit breakers and transaction rollback are therefore outside this implementation.

## API errors and recovery

Application errors return JSON with `detail`, `code` and `request_id`. `detail` is a readable string, except setup validation, which retains the familiar list of `{loc, msg, type}` errors. Supplied values, validation context and raw exception text are omitted. The request ID also appears in `X-Request-ID` and in diagnostics for unexpected failures. Trusted-host rejection is handled by Starlette before the route and retains its plain 400 response.

| Status | Code | Meaning and recovery |
| --- | --- | --- |
| 400 | `invalid_content_length`, `invalid_session`, `client_disconnected` | The length or session headers are invalid, or the upload ended early. Correct the request; refresh the client if its session headers are malformed. |
| 403 | `cross_origin` | A write came from another origin or an invalid origin. Use the local page served by this process. |
| 408 | `upload_timeout` | Body receipt exceeded five seconds. Send a fresh request. |
| 409 | `stale_frame` | Stop, Reset, setup or service instance changed. Discard the result and use the current response headers for subsequent frames. |
| 409 | `frame_expired` | The admitted request is more than 1.5 seconds old. Its observation is discarded and the visit ends. Send a fresh frame. |
| 413 | `body_too_large` | The encoded image exceeds 2,000,000 bytes or setup JSON exceeds 16,384 bytes. Reduce the body. |
| 415 | `invalid_content_type` | Inference requires `image/jpeg`; setup requires `application/json`. |
| 422 | `invalid_frame`, `invalid_frame_size`, `invalid_config` | The frame or setup is invalid. Correct the input; invalid setup leaves the saved configuration unchanged. |
| 429 | `inference_busy` | One upload or native inference is still active. Do not queue another frame; try a fresh one after it finishes. |
| 503 | `model_unavailable` | Model startup failed. Run `scripts/download_models.py`, check installation and restart the service. |
| 503 | `inference_failed` | The native pipeline or result processing failed. The affected visit ends. Stop the camera and check the local log. |
| 503 | `inference_timeout` | Native inference exceeded 15 seconds. The visit ends, but the native worker keeps its slot until it finishes. Restart the service if it remains stuck. |
| 500 | `internal_error` | An unexpected route failure reached the final error boundary. Stop capture and inspect the log using the request ID. |

Other HTTP exceptions retain their status and use `http_<status>` as their code. Existing successful response bodies are unchanged.

## Session ordering

Every response includes these headers:

| Header | Value |
| --- | --- |
| `X-Session-Instance` | A 32-character lowercase hexadecimal UUID generated for this application instance. It is an ordering identifier, not a secret or authentication token. |
| `X-Session-Generation` | A decimal counter starting at zero, incremented by Stop, Reset and successful setup changes. |

The browser captures both values before encoding a frame and supplies both on `POST /api/infer`. A missing half, malformed instance or malformed counter returns 400. A valid pair that does not match the current service returns 409 before native inference.

The client advances the counter within one instance. It adopts a different instance only if the request that produced the response began against the instance still considered current. This permits restart recovery and ignores a late response from a retired instance. Error responses also update the ordering pair, allowing a 409 to supply the next valid values. Client tests cover restart to generation zero and late responses.

Legacy clients may omit both headers. They retain the existing API contract and the check against controls that happen while their request is in flight. They cannot distinguish a pre-control frame that arrives at the server afterwards. Use both headers for the browser's full ordering protection.

## Input and resource boundaries

Body readers check declared length before reading and count actual streamed bytes before extending their buffer. They reject a mismatch between declared and received size. Both setup and frame uploads have a five-second receipt deadline.

JPEG input must contain its opening and closing markers. The parser reads frame dimensions before calling OpenCV. Each side must be 120 to 1,920 pixels, bounding the decoded BGR image to about 10.5 MiB. OpenCV must return matching dimensions. Decoder exceptions become 422 responses.

The admission lock covers receipt, decoding, native work and state processing. Native work is shielded from request cancellation. If the HTTP task ends first, a completion callback consumes the result, clears the task reference and releases the slot. Other inference requests receive 429 immediately; they are not added to a model work queue. Stop, Reset, setup and state reads can still proceed while the native worker runs.

Images and request buffers stay in memory. The server does not write them to disk or include them in its diagnostic records. Shutdown invalidates the current generation, ends the journey and drains outstanding native work before releasing the pipeline reference.

## Diagnostics and boundaries

Unexpected failures log an event name, request ID, exception class and function/line stack locations. Raw exception text, request bodies, frame pixels and local variables are excluded. Expected validation errors do not produce exception logs. Native inference deadlines produce a warning.

Security and no-cache headers are also attached to expected error responses. Writes require the same origin, including the scheme, and malformed origin values are rejected. The service still requires loopback binding and is not an authenticated multi-user server.

A deadline limits how long the request waits; it cannot forcibly terminate OpenVINO inside a thread. A stuck native call can retain its frame and block inference and graceful shutdown until it exits or the process is stopped. Frame freshness is measured from handler admission, not from camera exposure. These limits remain explicit rather than being hidden behind automatic retries.
