"""Approximate gaze/shelf intersection. No person-specific calibration.

The camera is mounted in the vertical shelf plane, facing the shopper, level and
square to it. Camera x is image-right and y is up. Vision returns positive gaze z
towards the camera. Shelf x is left-to-right as seen by the shopper (opposite
camera x), and shelf y is measured up from its bottom. Distances are metres.
"""
import math

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ShelfConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    shelf_width_m: float = Field(default=1.2, ge=0.3, le=5)
    shelf_height_m: float = Field(default=0.6, ge=0.2, le=3)
    camera_height_m: float = Field(default=0.3, ge=0, le=3)
    camera_offset_m: float = Field(default=0, ge=-2.5, le=2.5)
    distance_m: float = Field(default=1, ge=0.35, le=4)
    horizontal_fov_deg: float = Field(default=65, ge=25, le=120)
    dwell_threshold_s: float = Field(default=1.5, ge=0.5, le=15)
    offer_hold_s: float = Field(default=8, ge=3, le=60)

    @model_validator(mode="after")
    def camera_on_shelf(self):
        if self.camera_height_m > self.shelf_height_m:
            raise ValueError("Camera height must be within the shelf height.")
        if abs(self.camera_offset_m) > self.shelf_width_m / 2:
            raise ValueError("Camera offset must be within the shelf width.")
        return self


def unknown(status, reason, point=None):
    return {"status": status, "zone": None, "point": point, "reason": reason}


def observe(result: dict, config: ShelfConfig) -> dict:
    faces = result.get("faces", [])
    if not faces:
        return unknown("no_face", "No visible face. Dwell is paused.")
    if len(faces) != 1:
        return unknown("multiple_people", "More than one face; showing a general message.")
    face = faces[0]
    if not face.get("usable"):
        return unknown("unreliable", face.get("quality_reason", "Eye signal unavailable."))
    gaze = face.get("gaze")
    centres = face.get("eye_centres")
    width, height = result.get("width", 0), result.get("height", 0)
    if not gaze or len(gaze) != 3 or not centres or len(centres) != 2 or width <= 0 or height <= 0:
        return unknown("unreliable", "Eye position or gaze direction unavailable.")
    if not all(math.isfinite(v) for v in [*gaze, *centres[0], *centres[1]]):
        return unknown("unreliable", "Invalid gaze measurement.")
    gx, gy, gz = gaze
    if gz <= 0.15:
        return unknown("away", "Gaze does not point towards the shelf plane.")
    # Square pixels; the horizontal FOV determines the focal length in pixels.
    focal = width / (2 * math.tan(math.radians(config.horizontal_fov_deg / 2)))
    eye_px = (centres[0][0] + centres[1][0]) / 2
    eye_py = (centres[0][1] + centres[1][1]) / 2
    eye_x = config.distance_m * (eye_px - width / 2) / focal
    eye_y = config.distance_m * (height / 2 - eye_py) / focal
    travel = config.distance_m / gz
    x = config.camera_offset_m - (eye_x + travel * gx)
    y = config.camera_height_m + eye_y + travel * gy
    point = {"x_m": round(x, 3), "y_m": round(y, 3)}
    half = config.shelf_width_m / 2
    if not (-half <= x <= half and 0 <= y <= config.shelf_height_m):
        return unknown("outside_shelf", "Estimated gaze falls outside the configured shelf.", point)
    # A small deliberate exclusion band avoids flickering at zone boundaries.
    # This is a heuristic, NOT a calibrated error bound or confidence interval.
    edge = config.shelf_width_m / 6
    margin = min(0.05, config.shelf_width_m / 24)
    if min(abs(x - edge), abs(x + edge)) < margin:
        return unknown("boundary", "Between shelf zones; waiting for a clearer direction.", point)
    zone = "left" if x < -edge else "right" if x > edge else "centre"
    return {"status": "estimated", "zone": zone, "point": point,
            "reason": "Approximate zone from eye gaze and operator geometry; not validated product attention."}
