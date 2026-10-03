# Functionality and build review

Reviewed on 3 October 2026. The implementation retains FastAPI, OpenVINO and plain browser JavaScript. There is no serverless deployment or database in this local prototype.

## State and API behaviour

`server.py` owns the application lifetime, active configuration, current `Journey`, model pipeline and inference admission lock. `api_support.py` handles bounded body receipt, JPEG validation, expected API errors and restricted diagnostic logging. Geometry and journey rules remain in their existing modules.

| Operation | State effect | Ordering protection |
| --- | --- | --- |
| Read status/configuration/state | Returns current state; journey snapshots expire old observations. | Response includes the current service instance and generation. |
| Save setup | Validates the complete submitted setup, replaces configuration, ends the visit, records a setup event. An invalid request preserves configuration. | Advances the generation. Both older successes and failures are discarded. |
| Reset | Replaces the journey, clearing visit totals and events. Retains setup. | Advances the generation. |
| Stop | Ends the current visit, clears dwell and the offer, and marks the camera inactive. Retains accumulated run totals. | Advances the generation. |
| Infer | Validates one frame, runs the local pipeline, computes the observation and updates the journey. | One admitted worker, instance/generation validation, in-flight generation check and a 1.5-second request-age limit. |

The session headers add ordering information without changing successful JSON body shapes. A legacy inference request that omits both headers remains accepted; its weaker delayed-arrival protection is documented in [Error handling](ERROR_HANDLING.md).

## Confirmed fixes

The five initially failing regressions are recorded in [Debugging report](DEBUG.md). They cover cancellation releasing the native-work slot too soon, stale inference failures, unlimited setup JSON, image dimensions checked after allocation and uncaught decoder errors.

The completed implementation also handles invalid origin syntax, mismatched request lengths, malformed model results, a native inference deadline and service restart ordering. Public errors include a code and request ID. Setup validation retains field-specific errors for the frontend to display.

## Verification

```sh
.venv/bin/python -m pytest tests/test_server.py -q
.venv/bin/python -m compileall -q server.py api_support.py
git diff --check
```

All 36 focused backend cases passed. Python compilation and whitespace checks passed. The pytest run includes one upstream Starlette TestClient deprecation warning about `httpx`.

The test suite exercises both normal frames and controlled concurrency with thread events. It checks stop/reset/setup during a failing inference, cancellation while native work is active, upload timeout recovery, native timeout admission, late-arriving frames and fresh headers after a service restart. It uses generated blank JPEGs and fake model pipelines. No raw camera recordings or biometric templates are fixtures.

The frontend has separate tests for its response ordering, camera lifecycle and request messages. Integrated browser evidence and any real-model smoke checks are recorded by the corresponding audit and performance reports. This report does not present simulated inference as hardware or shelf validation.

## Operational limits

The process serves one shared journey. Independent cameras, separate operators and multiple application workers would require a different state model. Run it with the supplied loopback launch command and one worker.

State is volatile. A restart discards configuration, totals, events and temporary visit IDs. Native execution cannot be forcibly cancelled from its Python thread; a permanent native hang can block further inference and graceful shutdown. The prototype's gaze and dwell values remain approximate, and physical shelf accuracy still requires a controlled measurement.
