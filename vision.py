# Adapted from Intel Open Model Zoo C++ gaze demo.
# Copyright (C) 2018-2024 Intel Corporation; SPDX-License-Identifier: Apache-2.0
# Changes and pinned source files: model-provenance.json.
"""Local OpenVINO face / eye / head-pose / gaze inference.

API axes: x = unmirrored image right; y = image up; z = towards the camera
from the shopper. The raw OMZ model's frontal output is negative z, so we
negate its z component, retaining the x/y used by OMZ's gaze arrows.
This is an approximate camera-relative direction, NOT a metric world ray,
gaze confidence, verified fixation, identity, or measure of attention.

Preprocessing and roll correction follow Intel's Apache-2.0 C++ gaze demo,
pinned in model-provenance.json. There is no face embedding or image storage.
"""
from __future__ import annotations

import math
from pathlib import Path
from threading import Lock
from time import perf_counter

import cv2
import numpy as np
import openvino as ov

FACE_MODEL = "face-detection-retail-0004"
LANDMARK_MODEL = "facial-landmarks-35-adas-0002"
HEAD_MODEL = "head-pose-estimation-adas-0001"
GAZE_MODEL = "gaze-estimation-adas-0002"
EYE_MODEL = "open-closed-eye-0001"


def _blob(image: np.ndarray, shape, *, eye_normalise: bool = False) -> np.ndarray:
    """BGR, NCHW float32; IR graphs already contain model preprocessing."""
    h, w = int(shape[2]), int(shape[3])
    resized = cv2.resize(image, (w, h), interpolation=cv2.INTER_CUBIC)
    value = resized.astype(np.float32)
    if eye_normalise:
        # This model is raw ONNX; reproduce its model.yml conversion arguments.
        value = (value - 127.0) / 255.0
    return np.ascontiguousarray(value.transpose(2, 0, 1)[None])


def _roll_eye(image: np.ndarray, roll_degrees: float) -> np.ndarray:
    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w // 2, h // 2), roll_degrees, 1.0)
    return cv2.warpAffine(image, matrix, (w, h),
                          flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def _adjust_face(rect: list[int]) -> list[int]:
    """OMZ face_detector.cpp adjustment: expand then square the face crop."""
    x, y, w, h = rect
    x -= int(0.067 * w)
    y -= int(0.028 * h)
    w += int(0.15 * w)
    h += int(0.13 * h)
    if w < h:
        x -= (h - w) // 2
        w = h
    else:
        y -= (w - h) // 2
        h = w
    return [x, y, w, h]


class _Model:
    def __init__(self, core: ov.Core, path: Path):
        self.compiled = core.compile_model(
            str(path), "CPU",
            {"PERFORMANCE_HINT": "LATENCY", "INFERENCE_NUM_THREADS": 2},
        )
        self.request = self.compiled.create_infer_request()
        self.inputs = {p.get_any_name(): p for p in self.compiled.inputs}

    def run(self, inputs: dict | np.ndarray) -> dict[str, np.ndarray]:
        if isinstance(inputs, np.ndarray):
            inputs = {next(iter(self.inputs)): inputs}
        results = self.request.infer(inputs)
        # Some IR outputs carry both legacy (fc_y) and runtime (angle_y_fc)
        # aliases. get_any_name() alone has nondeterministic alias selection.
        outputs = {}
        for port, value in results.items():
            array = value.copy()
            for name in port.get_names():
                outputs[name] = array
        return outputs

    def image(self, image: np.ndarray, *, eye_normalise: bool = False) -> dict:
        port = next(iter(self.inputs.values()))
        return self.run(_blob(image, port.shape, eye_normalise=eye_normalise))


class VisionPipeline:
    """Stateless per-frame inference; track IDs and dwell belong to the caller.

    Quality thresholds are conservative application heuristics, not calibrated
    model confidence bounds. Open eyes are classified from the two eye crops.
    'confidence' is exclusively the face detector's probability.
    """

    def __init__(
        self, model_dir: str | Path, *,
        face_threshold: float = 0.65, max_faces: int = 4,
        min_face_px: int = 64, min_eye_width_px: float = 10.0,
    ):
        self.model_dir = Path(model_dir)
        self.face_threshold = float(face_threshold)
        self.max_faces = max(1, int(max_faces))
        self.min_face_px = int(min_face_px)
        self.min_eye_width_px = float(min_eye_width_px)
        self._lock = Lock()
        core = ov.Core()
        self._models = {}
        for name in (FACE_MODEL, LANDMARK_MODEL, HEAD_MODEL, GAZE_MODEL):
            path = self.model_dir / name / f"{name}.xml"
            if not path.is_file() or not path.with_suffix(".bin").is_file():
                raise FileNotFoundError(
                    f"Missing model {name}. Run scripts/download_models.py."
                )
            self._models[name] = _Model(core, path)
        eye_path = self.model_dir / EYE_MODEL / "open-closed-eye.onnx"
        if not eye_path.is_file():
            raise FileNotFoundError(
                f"Missing model {EYE_MODEL}. Run scripts/download_models.py. "
                "Eye-state gating is required for gaze estimates."
            )
        self._eye_model = _Model(core, eye_path)
        self.metadata = {
            "device": "CPU", "openvino_version": ov.__version__,
            "models": list(self._models) + ([EYE_MODEL] if self._eye_model else []),
            "eyes_open_available": self._eye_model is not None,
            "gaze_axes": "x=image right; y=image up; z=shopper towards camera",
            "gaze_is_calibrated": False,
            "quality_thresholds_are_heuristics": True,
        }

    def infer(self, frame: np.ndarray) -> dict:
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("Expected an HxWx3 BGR numpy frame.")
        if frame.dtype != np.uint8 or min(frame.shape[:2]) < 2:
            raise ValueError("Expected a non-empty uint8 BGR frame.")
        started = perf_counter()
        height, width = frame.shape[:2]
        with self._lock:
            result = self._infer_locked(frame, width, height)
        return {
            "faces": result, "width": width, "height": height,
            "inference_ms": round((perf_counter() - started) * 1000, 2),
        }

    def _infer_locked(self, frame, width: int, height: int) -> list[dict]:
        output = self._models[FACE_MODEL].image(frame)
        rows = next(iter(output.values())).reshape(-1, 7)
        candidates = [
            r for r in rows
            if r[0] >= 0 and np.isfinite(r).all() and r[2] >= self.face_threshold
        ]
        candidates.sort(key=lambda r: float(r[2]), reverse=True)
        faces = []
        for row in candidates[:self.max_faces]:
            x0, y0, x1, y1 = row[3:7] * [width, height, width, height]
            rect = _adjust_face([int(x0), int(y0), int(x1 - x0), int(y1 - y0)])
            x, y, w, h = rect
            face = {
                "bbox": rect, "confidence": float(row[2]),
                "gaze": None, "head_pose": None, "eyes_open": None,
                "usable": False, "quality_reason": "",
                "eye_centres": [], "eye_open_probabilities": None,
            }
            if w < self.min_face_px or h < self.min_face_px:
                face["quality_reason"] = "face_too_small"
            elif x < 0 or y < 0 or x + w > width or y + h > height:
                face["quality_reason"] = "face_clipped"
            else:
                self._infer_face(frame, face)
            faces.append(face)
        return faces

    def _infer_face(self, frame: np.ndarray, face: dict) -> None:
        x, y, w, h = face["bbox"]
        crop = frame[y:y+h, x:x+w]
        head_out = self._models[HEAD_MODEL].image(crop)
        angles = np.array([
            float(head_out[key].reshape(-1)[0]) for key in ("fc_y", "fc_p", "fc_r")
        ], dtype=np.float32)
        if not np.isfinite(angles).all():
            face["quality_reason"] = "head_pose_invalid"
            return
        face["head_pose"] = angles.tolist()
        yaw, pitch, roll = angles
        # Deliberately narrower than the model's training limits; field testing
        # and calibration are still necessary before interpreting shelf zones.
        if abs(yaw) > 40 or abs(pitch) > 35 or abs(roll) > 35:
            face["quality_reason"] = "head_pose_extreme"
            return

        landmark_out = self._models[LANDMARK_MODEL].image(crop)
        landmarks = next(iter(landmark_out.values())).reshape(-1, 2)
        if len(landmarks) != 35 or not np.isfinite(landmarks).all():
            face["quality_reason"] = "eye_landmarks_invalid"
            return
        landmarks = landmarks * [w, h] + [x, y]
        centres = [(landmarks[0] + landmarks[1]) / 2,
                   (landmarks[2] + landmarks[3]) / 2]
        face["eye_centres"] = [c.tolist() for c in centres]
        eye_images = []
        image_h, image_w = frame.shape[:2]
        for index, centre in zip((0, 2), centres):
            eye_width = float(np.linalg.norm(landmarks[index] - landmarks[index+1]))
            if eye_width < self.min_eye_width_px:
                face["quality_reason"] = "eyes_too_small"
                return
            # Same 1.8 x corner-distance square as the upstream eye-state demo.
            size = int(1.8 * eye_width)
            ex, ey = int(centre[0]) - size // 2, int(centre[1]) - size // 2
            if ex < 0 or ey < 0 or ex + size > image_w or ey + size > image_h:
                face["quality_reason"] = "eye_crop_clipped"
                return
            eye_images.append(_roll_eye(frame[ey:ey+size, ex:ex+size], float(roll)))

        if self._eye_model is not None:
            probabilities = []
            for eye in eye_images:
                values = next(iter(self._eye_model.image(
                    eye, eye_normalise=True
                ).values())).reshape(-1)
                if len(values) != 2 or not np.isfinite(values).all():
                    face["quality_reason"] = "eye_state_invalid"
                    return
                # C++ EyeStateEstimator uses output[1] > output[0] for open.
                # model README lists these in reverse; upstream example-image
                # smoke checks are recorded in model-provenance.json.
                probabilities.append(float(values[1]))
            face["eye_open_probabilities"] = probabilities
            if min(probabilities) < 0.4:
                face["eyes_open"] = False
                face["quality_reason"] = "eyes_closed"
                return
            if min(probabilities) < 0.6:
                face["quality_reason"] = "eye_state_uncertain"
                return
            face["eyes_open"] = True

        model = self._models[GAZE_MODEL]
        inputs = {
            "left_eye_image": _blob(eye_images[0], model.inputs["left_eye_image"].shape),
            "right_eye_image": _blob(eye_images[1], model.inputs["right_eye_image"].shape),
            # Roll has already been removed from both eye crops.
            "head_pose_angles": np.array([[yaw, pitch, 0.0]], dtype=np.float32),
        }
        raw = next(iter(model.run(inputs).values())).reshape(-1).astype(np.float64)
        norm = float(np.linalg.norm(raw))
        if raw.size != 3 or not np.isfinite(raw).all() or norm < 1e-6:
            face["quality_reason"] = "gaze_invalid"
            return
        raw /= norm
        # Undo roll alignment using the exact upstream 2D rotation.
        cs, sn = math.cos(math.radians(float(roll))), math.sin(math.radians(float(roll)))
        direction = np.array([
            raw[0] * cs + raw[1] * sn,
            -raw[0] * sn + raw[1] * cs,
            -raw[2],
        ])
        face["gaze"] = direction.tolist()
        if direction[2] <= 0.1:
            face["quality_reason"] = "gaze_away_from_camera_plane"
            return
        face["usable"] = True
        face["quality_reason"] = "ok"
