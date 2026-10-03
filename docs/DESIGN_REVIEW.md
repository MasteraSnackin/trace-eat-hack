# Interface review

Trace keeps its local Python service and plain JavaScript pages. This review preserves the existing layout and concentrates on state feedback, recovery and accurate wording. The supplied brief's framework and visual-style examples do not fit this repository and were not added.

## Evidence

The starting operator page was captured and inspected in the in-app browser at `http://127.0.0.1:4322`. The saved image is [the initial operator view](screenshots/01-before-operator.jpg). It shows a clear two-column layout: camera and gaze results above setup and visit activity. The cream background, restrained green palette and separate camera area already give the controls a clear hierarchy.

The parent review reproduced a validation failure in the browser: with a shelf height of `0.6`, entering camera height `2` produced only `Could not save: The local service returned 422.` The captured evidence is [the initial validation error](screenshots/02-before-invalid-setup.jpg).

The request races below were identified in source and reproduced in automated JavaScript tests with controlled requests and a small DOM substitute. These tests exercise the production scripts, but they do not prove browser layout, camera access, screen-reader behaviour or physical gaze accuracy.

## Corrections

| Finding | Change | Regression evidence |
| --- | --- | --- |
| A hanging customer-display request could leave a specific offer visible indefinitely. | The shared request helper gives display requests a two-second deadline. Failure clears the offer and the next poll can recover. | A held request expires, clears the specific message and zone, then the next successful poll restores current state. |
| Most control and status requests had no deadline. | They now have a five-second deadline. Inference retains a separate twenty-second deadline. Aborted and timed-out requests release their timers. | Hung transport, external cancellation and malformed JSON tests. |
| The setup form discarded edits made while a save was in progress. | A field-edit revision keeps newer input and says that those edits are not saved. | A delayed response arrives after the field changes; the newer value remains. |
| Start became available before Stop was acknowledged. | Restart remains disabled until Stop finishes. The current offer and gaze are cleared immediately. | A held Stop response cannot leave the previous offer visible or permit an immediate restart. |
| A delayed status response could restore state from before a reset. | A UI revision prevents responses from earlier controls replacing current state. | A delayed status response cannot restore an old visit ID or dwell duration after reset. |
| A failed browser JPEG encoding left the camera marked as live with no future frames. | A missing encoded frame stops the camera with a recovery message. | Null encoding reaches the stopped state and explains the failure. |
| Old gaze could remain visible while inference stalled. | Current gaze, face statistics, arrow and specific offer clear after the last received observation is over 1.5 seconds old. The check runs every 250 ms. Historical totals remain available. | Stale-observation test clears the current estimate and offer. |
| Slow or obsolete server frames could retain an old offer. | HTTP 409 clears the current estimate and retries within the same server session. A changed server instance instead pauses capture for setup review. Expired frames have a specific explanation. | Expired-frame test checks clearing and a scheduled next frame. |
| A frame sent before Stop could arrive after it. | Frames carry the server instance and generation captured before asynchronous JPEG encoding. The backend rejects an obsolete pair. | The frontend preserves the pre-encoding token; backend tests cover rejection. |
| A server restart could make a monotonically stored generation invalid. | Tokens advance within a server instance. A response from a new instance can reset the generation; an older request cannot restore a retired instance. | Restart to generation zero, error-response adoption and late-response tests. |
| A restart left old shelf measurements visible while the server used defaults. | Capture stops when the server instance changes. Saved settings reload, unsaved edits stay in the form, and Start remains disabled until the operator saves the reviewed setup. | Tests cover clean and dirty forms, status-detected restarts and inference-detected restarts. |
| Navigation could leave a queued frame alive after camera tracks stopped. | Page hiding for navigation invalidates the frame generation, cancels the timer, aborts the pending frame and marks capture stopped. Restoring the page checks the service without starting capture. | Tests cover page restoration, queued frames and a camera permission response arriving after navigation. |
| Pydantic validation details were reduced to a generic status number. | The request helper presents string or field-array details, strips the leading Pydantic `Value error, ` prefix and retains the backend error code. | A field validation test preserves the useful explanation and HTTP 422 code. |

The response helper lives in `static/client.js` and is loaded before each page script. There are no added runtime dependencies. When both session headers are absent, the server retains compatibility with older clients; those clients do not gain protection against old frames first arriving after Stop. The supplied frontend sends both headers.

The backend's 1.5-second frame-age limit starts when the request is received. It does not measure time from camera capture to server arrival. The frontend freshness check uses time since the last accepted response. Neither is a physical timing or gaze-accuracy measurement. Browser scheduling can delay JavaScript timers, particularly in a background page.

## Wording and access

The interface now describes estimated gaze rather than measured attention. It calls its identifiers temporary visit IDs. Copy keeps the distinction between gaze, product preference and completed purchases.

The existing reduced-motion stylesheet remains in place. Focus outlines now use the darker green from the existing palette. A skip link reaches the operator controls, the scrollable activity region can receive keyboard focus, save operations expose `aria-busy`, and customer connection status uses a live status region. Both pages explain that JavaScript is required when it is disabled.

A service restart requires the operator to review and save the shelf setup before starting capture again. Unsaved measurements are preserved. Ordinary tab switches do not stop the camera; navigation and browser page restoration use the cleanup described above.

The setup and reset controls show pending feedback immediately. They do not claim a save or reset succeeded until the service confirms it. A failed request gives a recovery message instead of fabricating an empty successful result.

## Checks and limits

The following commands passed after the frontend changes:

```sh
node --test tests/*.mjs
node --check static/client.js
node --check static/app.js
node --check static/display.js
```

The JavaScript suite currently contains 19 tests. It uses Node's built-in test runner, virtual timers and controlled request responses. Node is needed for this suite, not for running the application.

The layout, spacing, colours, illustrations and responsive breakpoints are otherwise preserved. The final scoped visual assessment and its rubric are in [AUDIT.md](AUDIT.md); they do not constitute an accessibility certification, performance measurement or user study. Webcam hardware, gaze accuracy and shopper trials remain separate checks.

## Browser follow-up

The final browser review verified desktop and 390 px mobile layouts, visible keyboard focus, the skip link, field-specific validation, successful saves, reset and connection recovery. A real service restart reloaded the default shelf width and disabled Start until setup was saved again. Screenshots and before/after browser recordings are indexed in [AUDIT.md](AUDIT.md).

The final mobile capture also confirmed that the decorative offer circle no longer masks text. The preview now isolates its stacking context and places every text child above the decoration.
