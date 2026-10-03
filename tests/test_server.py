import threading

import cv2
from fastapi.testclient import TestClient
import numpy as np

from server import create_app


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


def test_model_failure_is_visible_and_does_not_generate_fake_data():
    def fail():
        raise FileNotFoundError("Test model missing")
    with TestClient(create_app(fail)) as client:
        state = client.get("/api/status").json()
        assert state["ready"] is False
        assert "Test model missing" in state["model_error"]
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
