import asyncio
import threading
from types import SimpleNamespace

import cv2
from fastapi.testclient import TestClient
import numpy as np
import httpx
import pytest

from server import create_app
import api_support
import server


class BlankPipeline:
    def infer(self, frame):
        height, width = frame.shape[:2]
        return {"faces": [], "width": width, "height": height, "inference_ms": 0.1}


def jpeg():
    ok, data = cv2.imencode(".jpg", np.zeros((480, 640, 3), np.uint8))
    assert ok
    return data.tobytes()


def test_status_inference_and_stop_contract():
    with TestClient(create_app(BlankPipeline)) as client:
        assert client.get("/api/status").json()["ready"] is True
        response = client.post("/api/infer", content=jpeg(), headers={"Content-Type": "image/jpeg"})
        assert response.status_code == 200
        assert response.json()["observation"]["status"] == "no_face"
        assert response.headers["cache-control"] == "no-store"
        assert client.post("/api/stop").json()["camera_active"] is False


def test_model_failure_is_visible_and_does_not_expose_exception_text(caplog):
    def fail():
        raise FileNotFoundError("private/model/path secret text")
    with TestClient(create_app(fail)) as client:
        state = client.get("/api/status").json()
        assert state["ready"] is False
        assert "scripts/download_models.py" in state["model_error"]
        assert "private/model/path" not in str(state)
        assert "secret text" not in caplog.text
        assert "FileNotFoundError" in caplog.text
        assert client.post("/api/infer", content=jpeg(), headers={"Content-Type": "image/jpeg"}).status_code == 503


def test_invalid_input_and_cross_origin_controls_rejected():
    with TestClient(create_app(BlankPipeline)) as client:
        assert client.post("/api/infer", content="bad").status_code == 415
        assert client.post("/api/infer", content=b"bad", headers={"Content-Type": "image/jpeg"}).status_code == 422
        assert client.post("/api/infer", content=b"x" * 2_000_001, headers={"Content-Type": "image/jpeg"}).status_code == 413
        assert client.post("/api/reset", headers={"Origin": "https://other.example"}).status_code == 403
        assert client.get("/api/status", headers={"Host": "other.example"}).status_code == 400
        assert client.post("/api/config", json={"distance_m": -1}).status_code == 422


def test_stopped_session_cannot_be_revived_by_inflight_frame():
    entered, release = threading.Event(), threading.Event()
    class SlowPipeline(BlankPipeline):
        def infer(self, frame):
            entered.set()
            assert release.wait(3)
            return super().infer(frame)
    with TestClient(create_app(SlowPipeline)) as client:
        responses = []
        thread = threading.Thread(target=lambda: responses.append(client.post("/api/infer", content=jpeg(), headers={"Content-Type": "image/jpeg"})))
        thread.start()
        assert entered.wait(3)
        assert client.post("/api/stop").status_code == 200
        release.set()
        thread.join(3)
        assert responses[0].status_code == 409
        assert client.get("/api/state").json()["camera_active"] is False


def test_setup_request_body_has_a_limit():
    with TestClient(create_app(BlankPipeline)) as client:
        response = client.post("/api/config", content=b" " * 20_000 + b"{}",
                               headers={"Content-Type": "application/json"})
        assert response.status_code == 413


def test_oversized_jpeg_dimensions_rejected_before_decoding(monkeypatch):
    ok, image = cv2.imencode(".jpg", np.zeros((120, 1921, 3), np.uint8))
    assert ok
    calls = []
    original = cv2.imdecode
    monkeypatch.setattr(cv2, "imdecode", lambda *args: calls.append(True) or original(*args))
    with TestClient(create_app(BlankPipeline)) as client:
        response = client.post("/api/infer", content=image.tobytes(),
                               headers={"Content-Type": "image/jpeg"})
        assert response.status_code == 422
        assert calls == []


def test_decoder_error_is_recoverable(monkeypatch):
    def fail(*args):
        raise cv2.error("decoder rejected image")
    monkeypatch.setattr(cv2, "imdecode", fail)
    with TestClient(create_app(BlankPipeline), raise_server_exceptions=False) as client:
        response = client.post("/api/infer", content=jpeg(), headers={"Content-Type": "image/jpeg"})
        assert response.status_code == 422


@pytest.mark.parametrize("control", ["/api/stop", "/api/reset", "/api/config"])
def test_failing_old_inference_is_discarded_after_control(control):
    entered, release = threading.Event(), threading.Event()

    class FailingPipeline(BlankPipeline):
        def infer(self, frame):
            entered.set()
            assert release.wait(3)
            raise RuntimeError("old frame failed")

    with TestClient(create_app(FailingPipeline)) as client:
        responses = []
        thread = threading.Thread(target=lambda: responses.append(client.post(
            "/api/infer", content=jpeg(), headers={"Content-Type": "image/jpeg"})))
        thread.start()
        try:
            assert entered.wait(3)
            client.post(control, json={} if control == "/api/config" else None)
        finally:
            release.set()
            thread.join(3)
        assert responses[0].status_code == 409


def test_cancellation_does_not_admit_a_second_native_worker():
    entered, release = threading.Event(), threading.Event()

    class SlowPipeline(BlankPipeline):
        def infer(self, frame):
            entered.set()
            assert release.wait(3)
            return super().infer(frame)

    async def scenario():
        app = create_app(SlowPipeline)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                pending = asyncio.create_task(client.post(
                    "/api/infer", content=jpeg(), headers={"Content-Type": "image/jpeg"}))
                try:
                    assert await asyncio.to_thread(entered.wait, 3)
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
                    response = await client.post("/api/infer", content=jpeg(),
                                                 headers={"Content-Type": "image/jpeg"})
                    assert response.status_code == 429
                finally:
                    release.set()

    asyncio.run(scenario())


@pytest.mark.parametrize("body", [b"", b"\xff\xd8", b"\xff\xd8\xff\xc0\x00\x01\xff\xd9", b"\xff\xd8\xff\xe0\xff\xff\xff\xd9"])
def test_malformed_jpegs_fail_without_entering_pipeline(body):
    class UnusedPipeline:
        def infer(self, frame):
            pytest.fail("An invalid frame reached inference")
    with TestClient(create_app(UnusedPipeline)) as client:
        response = client.post("/api/infer", content=body, headers={"Content-Type": "image/jpeg"})
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_frame"
        assert response.headers["x-request-id"] == response.json()["request_id"]


@pytest.mark.parametrize("declared, status", [("2000001", 413), ("invalid", 400), ("-1", 400), ("0", 400)])
def test_frame_content_length_validation(declared, status):
    with TestClient(create_app(BlankPipeline)) as client:
        response = client.post("/api/infer", content=jpeg(),
                               headers={"Content-Type": "image/jpeg", "Content-Length": declared})
        assert response.status_code == status


def test_invalid_setup_preserves_config_and_excludes_supplied_data():
    with TestClient(create_app(BlankPipeline)) as client:
        original = client.get("/api/config").json()
        response = client.post("/api/config", json={"shelf_height_m": 0.6, "camera_height_m": 2})
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_config"
        assert "Camera height" in response.json()["detail"][0]["msg"]
        assert "input" not in response.json()["detail"][0]
        assert client.get("/api/config").json() == original


@pytest.mark.parametrize("origin", ["http://[", "https://testserver", "http://testserver/path", "null"])
def test_invalid_or_cross_scheme_origin_is_rejected_with_security_headers(origin):
    with TestClient(create_app(BlankPipeline)) as client:
        response = client.post("/api/reset", headers={"Origin": origin})
        assert response.status_code == 403
        assert response.json()["code"] == "cross_origin"
        assert response.headers["cache-control"] == "no-store"


def test_internal_result_error_stops_session_and_is_recoverable(caplog):
    class MalformedPipeline:
        def infer(self, frame):
            return {"faces": [{"usable": False}], "width": 640, "height": 480}

    with TestClient(create_app(MalformedPipeline)) as client:
        response = client.post("/api/infer", content=jpeg(), headers={"Content-Type": "image/jpeg"})
        assert response.status_code == 503
        assert response.json()["code"] == "inference_failed"
        assert client.get("/api/state").json()["camera_active"] is False
        assert "KeyError" in caplog.text
        assert response.json()["request_id"] in caplog.text


def test_slow_result_cannot_be_recorded_as_current_attention(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(server, "time", SimpleNamespace(monotonic=lambda: now[0]))

    class OldPipeline(BlankPipeline):
        def infer(self, frame):
            now[0] += 2
            return super().infer(frame)

    with TestClient(create_app(OldPipeline)) as client:
        response = client.post("/api/infer", content=jpeg(), headers={"Content-Type": "image/jpeg"})
        assert response.status_code == 409
        assert response.json()["code"] == "frame_expired"
        state = client.get("/api/state").json()
        assert state["camera_active"] is False
        assert state["visits"] == 0


def test_inference_timeout_keeps_worker_bounded_and_recovers(monkeypatch):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    monkeypatch.setattr(server, "INFERENCE_TIMEOUT_S", 0.05)

    class SlowOncePipeline(BlankPipeline):
        calls = 0
        def infer(self, frame):
            self.calls += 1
            if self.calls == 1:
                entered.set()
                assert release.wait(3)
                finished.set()
            return super().infer(frame)

    with TestClient(create_app(SlowOncePipeline)) as client:
        try:
            response = client.post("/api/infer", content=jpeg(), headers={"Content-Type": "image/jpeg"})
            assert entered.is_set()
            assert response.status_code == 503
            assert response.json()["code"] == "inference_timeout"
            assert client.post("/api/infer", content=jpeg(), headers={"Content-Type": "image/jpeg"}).status_code == 429
        finally:
            release.set()
        assert finished.wait(3)
        # A control request crosses the event loop after worker completion.
        client.post("/api/stop")
        assert client.post("/api/infer", content=jpeg(), headers={"Content-Type": "image/jpeg"}).status_code == 200


def test_upload_deadline_releases_inference_slot(monkeypatch):
    monkeypatch.setattr(api_support, "UPLOAD_TIMEOUT_S", 0.02)

    async def slow_upload():
        yield b"\xff\xd8"
        await asyncio.sleep(1)
        yield b"\xff\xd9"

    async def scenario():
        app = create_app(BlankPipeline)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                response = await client.post("/api/infer", content=slow_upload(), headers={"Content-Type": "image/jpeg"})
                assert response.status_code == 408
                assert response.json()["code"] == "upload_timeout"
                assert (await client.post("/api/infer", content=jpeg(), headers={"Content-Type": "image/jpeg"})).status_code == 200

    asyncio.run(scenario())


def session_headers(response):
    return {"X-Session-Instance": response.headers["x-session-instance"],
            "X-Session-Generation": response.headers["x-session-generation"],
            "Content-Type": "image/jpeg"}


@pytest.mark.parametrize("control", ["/api/stop", "/api/reset", "/api/config"])
def test_delayed_frame_from_before_control_cannot_restart_visit(control):
    with TestClient(create_app(BlankPipeline)) as client:
        old_headers = session_headers(client.get("/api/status"))
        changed = client.post(control, json={} if control == "/api/config" else None)
        response = client.post("/api/infer", content=jpeg(), headers=old_headers)
        assert response.status_code == 409
        assert response.json()["code"] == "stale_frame"
        assert client.get("/api/state").json()["camera_active"] is False
        assert client.post("/api/infer", content=jpeg(), headers=session_headers(changed)).status_code == 200


def test_restarted_service_rejects_old_instance_and_accepts_fresh_headers():
    with TestClient(create_app(BlankPipeline)) as client:
        old_headers = session_headers(client.post("/api/stop"))
    with TestClient(create_app(BlankPipeline)) as restarted:
        current = restarted.get("/api/status")
        fresh_headers = session_headers(current)
        assert fresh_headers["X-Session-Instance"] != old_headers["X-Session-Instance"]
        assert fresh_headers["X-Session-Generation"] == "0"
        assert restarted.post("/api/infer", content=jpeg(), headers=old_headers).status_code == 409
        assert restarted.post("/api/infer", content=jpeg(), headers=fresh_headers).status_code == 200


@pytest.mark.parametrize("extra", [
    {"X-Session-Instance": "a" * 32}, {"X-Session-Generation": "0"},
    {"X-Session-Instance": "a" * 32, "X-Session-Generation": "not-a-number"},
    {"X-Session-Instance": "not-an-instance", "X-Session-Generation": "0"},
])
def test_incomplete_or_invalid_session_headers_are_rejected(extra):
    with TestClient(create_app(BlankPipeline)) as client:
        response = client.post("/api/infer", content=jpeg(), headers={"Content-Type": "image/jpeg", **extra})
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_session"
