"""Local-only webcam gaze service. Images are processed in memory and discarded."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import time
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from api_support import (ApiError, INFERENCE_TIMEOUT_S, LOGGER, MAX_CONFIG_BYTES,
                         MAX_IMAGE_BYTES, decode_frame, log_failure, read_body)
from events import Journey, MAX_SAMPLE_GAP
from geometry import ShelfConfig, observe

ROOT = Path(__file__).resolve().parent


def default_pipeline():
    from vision import VisionPipeline
    return VisionPipeline(ROOT / "models")


def create_app(pipeline_factory=default_pipeline):
    config = ShelfConfig()
    journey = Journey(config)
    pipeline = None
    model_error = None
    session_instance = uuid4().hex
    generation = 0
    inference_lock = asyncio.Lock()
    native_task = None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal pipeline, model_error, generation
        try:
            pipeline = await asyncio.to_thread(pipeline_factory)
        except Exception as exc:
            log_failure("model_start_failed", exc, "startup")
            model_error = "Gaze models could not be loaded. Run scripts/download_models.py, then restart the local service."
        try:
            yield
        finally:
            generation += 1
            journey.stop("Local server closed.")
            if native_task is not None:
                # Python cannot cancel an OpenVINO call already running in a
                # thread. Keep its model alive until that call has finished.
                try:
                    await asyncio.shield(native_task)
                except Exception:
                    pass  # The request or completion callback records failures.
            pipeline = None

    app = FastAPI(title="Shelf Trace", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    def error_response(request, status, detail, code, headers=None):
        return JSONResponse({"detail": detail, "code": code,
                             "request_id": getattr(request.state, "request_id", None)},
                            status_code=status, headers=headers)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error_response(request, exc.status_code, exc.detail,
                              getattr(exc, "code", f"http_{exc.status_code}"), exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        errors = [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
                  for error in exc.errors()]
        return error_response(request, 422, errors, "invalid_config")

    @app.middleware("http")
    async def local_requests_only(request: Request, call_next):
        request.state.request_id = uuid4().hex[:12]
        # No cross-origin writes or CORS support: another website may not control
        # the local camera session. Loopback binding is still required at launch.
        response = None
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            try:
                parsed = urlparse(origin) if origin else None
                bad_origin = parsed is not None and (
                    parsed.netloc != request.headers.get("host") or parsed.scheme != request.url.scheme
                    or parsed.path or parsed.params or parsed.query or parsed.fragment
                )
            except ValueError:
                bad_origin = True
            if request.headers.get("sec-fetch-site") == "cross-site" or bad_origin:
                response = error_response(request, 403, "Only same-origin local controls are accepted.", "cross_origin")
        if response is None:
            try:
                response = await call_next(request)
            except Exception as exc:
                log_failure("request_failed", exc, request.state.request_id)
                response = error_response(request, 500,
                    "The local service could not complete this request. Stop the camera and check the server log.",
                    "internal_error")
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Session-Instance"] = session_instance
        response.headers["X-Session-Generation"] = str(generation)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.get("/api/status")
    async def status():
        return {"ready": pipeline is not None, "model_error": model_error,
                "model_info": getattr(pipeline, "metadata", None),
                "config": config.model_dump(), "state": journey.snapshot(time.monotonic())}

    @app.get("/api/config")
    async def get_config():
        return config.model_dump()

    @app.post("/api/config")
    async def set_config(request: Request):
        nonlocal config, generation
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise ApiError(415, "invalid_content_type", "Send shelf setup as JSON.")
        body = await read_body(request, MAX_CONFIG_BYTES, "Shelf setup exceeds 16 KiB.")
        try:
            updated = ShelfConfig.model_validate_json(body)
        except ValidationError as exc:
            errors = exc.errors(include_url=False, include_input=False, include_context=False)
            for error in errors:
                error["loc"] = ("body", *error["loc"])
            raise RequestValidationError(errors) from None
        config = updated
        generation += 1
        journey.stop("Shelf setup changed; previous dwell discarded.")
        journey.config = config
        journey.event("setup_changed", "Operator shelf geometry updated. Accuracy still requires a physical check.")
        return config.model_dump()

    @app.get("/api/state")
    async def get_state():
        return journey.snapshot(time.monotonic())

    @app.post("/api/reset")
    async def reset():
        nonlocal journey, generation
        generation += 1
        journey = Journey(config)
        return journey.snapshot(time.monotonic())

    @app.post("/api/stop")
    async def stop():
        nonlocal generation
        generation += 1
        journey.stop()
        return journey.snapshot(time.monotonic())

    @app.post("/api/infer")
    async def infer(request: Request):
        nonlocal native_task
        if pipeline is None:
            raise ApiError(503, "model_unavailable", model_error or "Gaze model is not ready.")
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "image/jpeg":
            raise ApiError(415, "invalid_content_type", "Send a JPEG camera frame.")
        supplied_instance = request.headers.get("x-session-instance")
        supplied_generation = request.headers.get("x-session-generation")
        if supplied_instance is not None or supplied_generation is not None:
            if (supplied_instance is None or supplied_generation is None
                    or len(supplied_instance) != 32
                    or any(char not in "0123456789abcdef" for char in supplied_instance)
                    or not supplied_generation.isascii() or not supplied_generation.isdigit()
                    or len(supplied_generation) > 20):
                raise ApiError(400, "invalid_session", "Camera session headers are invalid. Refresh the page and try again.")
            if supplied_instance != session_instance or int(supplied_generation) != generation:
                raise ApiError(409, "stale_frame", "Frame discarded because the camera session or local service changed.")
        if inference_lock.locked():
            raise ApiError(429, "inference_busy", "A camera frame is still being processed. Wait before sending another.")
        await inference_lock.acquire()
        request_generation = generation
        request_started = time.monotonic()
        worker = None

        def discard_if_stale():
            if generation != request_generation:
                raise ApiError(409, "stale_frame", "Frame discarded because the camera session or shelf setup changed.")

        def discard_if_old():
            if time.monotonic() - request_started > MAX_SAMPLE_GAP:
                journey.stop("Camera frame arrived too late; visit ended.")
                raise ApiError(409, "frame_expired", "Camera frame arrived too late and was discarded. Waiting for a fresh frame.")

        def release_after_worker(completed):
            nonlocal native_task
            try:
                completed.result()
            except asyncio.CancelledError:
                LOGGER.warning("worker_cancelled request_id=%s", request.state.request_id)
            except Exception as exc:
                log_failure("discarded_inference_failed", exc, request.state.request_id)
            finally:
                if native_task is completed:
                    native_task = None
                inference_lock.release()

        try:
            body = await read_body(request, MAX_IMAGE_BYTES, "Camera frame exceeds 2 MB.")
            discard_if_stale()
            discard_if_old()
            frame = decode_frame(body)
            del body
            worker = native_task = asyncio.create_task(asyncio.to_thread(pipeline.infer, frame))
            del frame
            try:
                result = await asyncio.wait_for(asyncio.shield(worker), INFERENCE_TIMEOUT_S)
                if await request.is_disconnected():
                    discard_if_stale()
                    journey.stop("Camera request disconnected; visit ended.")
                    raise ApiError(400, "client_disconnected", "The camera request was disconnected.")
                discard_if_stale()
                discard_if_old()
                # Reject invalid internal results before committing visit state.
                # The real pipeline returns ordinary finite JSON values.
                json.dumps(result, allow_nan=False)
                observation = observe(result, config)
                result["observation"] = observation
                result["state"] = journey.process(observation, result, time.monotonic())
                return result
            except TimeoutError:
                discard_if_stale()
                journey.stop("Inference timed out; camera session paused.")
                LOGGER.warning("inference_timeout request_id=%s", request.state.request_id)
                raise ApiError(503, "inference_timeout",
                    "Gaze inference took too long. Stop the camera. If the service stays busy, restart it.") from None
            except ApiError:
                raise
            except Exception as exc:
                log_failure("inference_failed", exc, request.state.request_id)
                discard_if_stale()
                journey.stop("Inference failed; camera session paused.")
                raise ApiError(503, "inference_failed",
                    "Gaze inference failed. Stop the camera and check the local model installation.") from None
        except asyncio.CancelledError:
            if generation == request_generation:
                journey.stop("Camera request cancelled; visit ended.")
            raise
        finally:
            if worker is not None and not worker.done():
                # Cancelling an await does not stop native inference. Keep one
                # worker admitted until it exits; do not build a thread queue.
                worker.add_done_callback(release_after_worker)
            else:
                if worker is not None and not worker.cancelled():
                    # A result can finish at the same instant as a deadline.
                    # Retrieve its exception even when the timeout won the race.
                    worker.exception()
                if native_task is worker:
                    native_task = None
                inference_lock.release()

    @app.get("/")
    async def index():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/display")
    async def display():
        return FileResponse(ROOT / "static" / "display.html")

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app


app = create_app()
