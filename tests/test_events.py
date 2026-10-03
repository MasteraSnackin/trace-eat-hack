import pytest

from events import Journey, MAX_SAMPLE_GAP, VISIT_GAP
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


@pytest.mark.parametrize("zone", ["left", "centre", "right"])
@pytest.mark.parametrize("gap", [MAX_SAMPLE_GAP + 0.000001, 1.75, VISIT_GAP])
def test_stale_offer_expires_with_dwell_before_visit_timeout(zone, gap):
    j = Journey(ShelfConfig())
    for now in (0, .75, 1.5):
        before = at(j, now, zone)
    assert before["offer"]["zone"] == zone

    state = j.snapshot(1.5 + gap)

    assert state["offer"]["kind"] == "general"
    assert state["offer"]["zone"] is None
    assert state["current_zone"] is None
    assert state["dwell_s"] == 0
    assert state["session_id"] == before["session_id"]
    assert state["zone_totals"] == before["zone_totals"]
    assert state["events"] == before["events"]


def test_exact_sample_gap_keeps_current_offer():
    j = Journey(ShelfConfig())
    for now in (0, .75, 1.5):
        at(j, now)
    state = j.snapshot(1.5 + MAX_SAMPLE_GAP)
    assert state["offer"]["zone"] == "left"
    assert state["dwell_s"] == 1.5


def test_resumed_samples_requalify_after_stale_offer_without_display_poll():
    j = Journey(ShelfConfig())
    for now in (0, .75, 1.5):
        at(j, now)

    state = at(j, 3.25)
    assert state["offer"]["kind"] == "general"
    assert state["session_id"] == "Visit 001"
    assert state["dwell_s"] == 0
    assert at(j, 4)["offer"]["kind"] == "general"
    state = at(j, 4.75)
    assert state["offer"]["zone"] == "left"
    assert state["zone_totals"]["left"] == 3
    assert sum(event["type"] == "offer_shown" for event in state["events"]) == 2


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
