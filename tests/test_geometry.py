import math

import pytest
from pydantic import ValidationError

from geometry import ShelfConfig, observe


def sample(gaze=(0, 0, 1), **overrides):
    face = {"bbox": [260, 100, 120, 160], "confidence": 0.99, "usable": True,
            "eye_centres": [[300, 240], [340, 240]], "gaze": list(gaze), **overrides}
    return {"width": 640, "height": 480, "faces": [face]}


def test_centre_ray_hits_camera_position():
    result = observe(sample(), ShelfConfig())
    assert result["zone"] == "centre"
    assert result["point"] == {"x_m": 0, "y_m": .3}


@pytest.mark.parametrize("x, zone", [(.4, "left"), (-.4, "right")])
def test_camera_direction_maps_to_shopper_shelf_orientation(x, zone):
    assert observe(sample((x, 0, 1)), ShelfConfig())["zone"] == zone


def test_off_axis_eye_changes_intersection_even_with_same_gaze():
    result = observe(sample(eye_centres=[[480, 240], [520, 240]]), ShelfConfig())
    assert result["zone"] == "left"


@pytest.mark.parametrize("gaze,status", [((0, 0, -1), "away"), ((0, 1, 1), "outside_shelf"), ((.2, 0, 1), "boundary"), ((math.nan, 0, 1), "unreliable")])
def test_does_not_force_uncertain_or_outside_rays_into_a_zone(gaze, status):
    result = observe(sample(gaze), ShelfConfig())
    assert result["zone"] is None
    assert result["status"] == status


def test_multiple_people_and_bad_eye_signal_do_not_assign_zone():
    data = sample()
    data["faces"] *= 2
    assert observe(data, ShelfConfig())["status"] == "multiple_people"
    assert observe(sample(usable=False, quality_reason="Eyes closed"), ShelfConfig())["status"] == "unreliable"


@pytest.mark.parametrize("values", [{"distance_m": 0}, {"horizontal_fov_deg": math.nan}, {"camera_height_m": 2}, {"camera_offset_m": 2}, {"unknown_setting": 1}])
def test_impossible_geometry_is_rejected(values):
    with pytest.raises(ValidationError):
        ShelfConfig(**values)
