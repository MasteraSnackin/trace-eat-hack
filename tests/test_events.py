from events import Journey
from geometry import ShelfConfig


FACE = {"faces": [{"bbox": [100, 100, 100, 160]}]}


def at(journey, time, zone="left", faces=FACE):
    return journey.process({"zone": zone}, faces, time)


def test_continuous_dwell_triggers_one_offer_then_holds_on_zone_change():
    j = Journey(ShelfConfig())
    at(j, 0)
    at(j, .75)
    state = at(j, 1.5)
    assert state["offer"]["zone"] == "left"
    assert state["dwell_s"] == 1.5
    for t in range(2, 10):
        state = at(j, t, "right")
    assert state["offer"]["zone"] == "left"
    state = at(j, 10, "right")
    assert state["offer"]["zone"] == "right"
    assert sum(e["type"] == "offer_shown" for e in state["events"]) == 2


def test_unknown_frames_break_continuous_dwell():
    j = Journey(ShelfConfig())
    at(j, 0)
    at(j, 1)
    at(j, 1.1, None)
    state = at(j, 1.5)
    assert state["dwell_s"] == 0
    assert state["offer"]["kind"] == "general"


def test_missing_frames_do_not_count_offline_time():
    j = Journey(ShelfConfig())
    at(j, 0)
    at(j, 1)
    state = at(j, 3)
    assert state["dwell_s"] == 0
    assert state["zone_totals"]["left"] == 1


def test_stale_display_expires_even_without_new_inference():
    j = Journey(ShelfConfig())
    at(j, 0)
    at(j, 1)
    at(j, 2)
    state = j.snapshot(5)
    assert state["camera_active"] is False
    assert state["session_id"] is None
    assert state["offer"]["kind"] == "general"


def test_multiple_faces_clear_attribution_and_offer():
    j = Journey(ShelfConfig())
    at(j, 0)
    at(j, 1)
    at(j, 2)
    state = at(j, 2.2, None, {"faces": FACE["faces"] * 2})
    assert state["session_id"] is None
    assert state["offer"]["kind"] == "general"
    assert at(j, 2.4)["session_id"] == "Visit 002"


def test_no_face_and_stop_do_not_preserve_personal_offer():
    j = Journey(ShelfConfig())
    at(j, 0)
    at(j, 1)
    at(j, 2)
    assert at(j, 2.2, None, {"faces": []})["offer"]["kind"] == "general"
    j.stop()
    assert j.snapshot(2.3)["session_id"] is None


def test_abrupt_jump_creates_new_track_not_returning_identity():
    j = Journey(ShelfConfig())
    at(j, 0)
    state = at(j, 1, faces={"faces": [{"bbox": [500, 100, 100, 160]}]})
    assert state["session_id"] == "Visit 002"
    assert state["dwell_s"] == 0
