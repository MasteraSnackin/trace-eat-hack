"""Local-only webcam gaze service. Images are processed in memory and discarded."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import time
from urllib.parse import urlparse

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from events import Journey
from geometry import ShelfConfig, observe

ROOT = Path(__file__).resolve().parent
MAX_IMAGE_BYTES = 2_000_000


def default_pipeline():
    from vision import VisionPipeline
    return VisionPipeline(ROOT / "models")


def create_app(pipeline_factory=default_pipeline):
    config = ShelfConfig()
    journey = Journey(config)
    pipeline = None
    model_error = None
    generation = 0
    inference_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        nonlocal pipeline, model_error
        try:
            pipeline = await asyncio.to_thread(pipeline_factory)
        except Exception as exc:
            model_error = f"{type(exc).__name__}: {exc}"
        yield
        journey.stop("Local server closed.")

    app = FastAPI(title="Shelf Trace", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_requests_only(request: Request, call_next):
        # No cross-origin writes or CORS support: another website may not control
        # the local camera session. Loopback binding is still required at launch.
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            parsed = urlparse(origin) if origin else None
            if request.headers.get("sec-fetch-site") == "cross-site" or (
                parsed is not None and (parsed.netloc != request.headers.get("host") or parsed.scheme not in {"http", "https"})
            ):
                return JSONResponse({"detail": "Only same-origin local controls are accepted."}, status_code=403)
        response = await call_next(request)
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
    async def set_config(updated: ShelfConfig):
        nonlocal config, generation
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
        if pipeline is None:
            raise HTTPException(503, model_error or "Gaze model is not ready.")
        if request.headers.get("content-type", "").split(";")[0] != "image/jpeg":
            raise HTTPException(415, "Send a JPEG camera frame.")
        if inference_lock.locked():
            raise HTTPException(429, "A camera frame is still being processed.")
        async with inference_lock:
            request_generation = generation
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > MAX_IMAGE_BYTES:
                    raise HTTPException(413, "Camera frame exceeds 2 MB.")
            if not body.startswith(b"\xff\xd8"):
                raise HTTPException(422, "Invalid JPEG camera frame.")
            frame = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
            del body
            if frame is None or min(frame.shape[:2]) < 120 or max(frame.shape[:2]) > 1920:
                raise HTTPException(422, "Use a valid JPEG frame between 120 and 1920 pixels per side.")
            try:
                result = await asyncio.to_thread(pipeline.infer, frame)
            except Exception:
                journey.stop("Inference failed; camera session paused.")
                raise HTTPException(503, "Gaze inference failed. Stop the camera and check the local model installation.") from None
            finally:
                del frame
            if generation != request_generation:
                raise HTTPException(409, "Frame discarded because the camera session or shelf setup changed.")
            observation = observe(result, config)
            result["observation"] = observation
            result["state"] = journey.process(observation, result, time.monotonic())
            return result

    @app.get("/")
    async def index():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/display")
    async def display():
        return FileResponse(ROOT / "static" / "display.html")

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app


app = create_app()
