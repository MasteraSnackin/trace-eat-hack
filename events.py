"""Volatile, single-camera visit and dwell state. No biometric identity storage."""
from collections import deque
from datetime import datetime, timezone
import math

from geometry import ShelfConfig


GENERAL = {"title": "Find your next protein favourite", "detail": "Explore bars, drinks and snacks. Demo display — no live promotion.", "zone": None, "kind": "general"}
OFFERS = {
    "left": {"title": "Try a protein bar", "detail": "Example offer: 10% off a protein bar. Demo only — not redeemable.", "zone": "left", "kind": "demo"},
    "centre": {"title": "Discover a protein drink", "detail": "Example offer: a free drink sample. Demo only — not redeemable.", "zone": "centre", "kind": "demo"},
    "right": {"title": "A new snack to explore", "detail": "Example offer: 10% off a protein snack. Demo only — not redeemable.", "zone": "right", "kind": "demo"},
}
MAX_SAMPLE_GAP = 1.5
VISIT_GAP = 2.5


class Journey:
    def __init__(self, config: ShelfConfig):
        self.config = config
        self.visits = 0
        self.events = deque(maxlen=80)
        self.zone_totals = {z: 0.0 for z in OFFERS}
        self.session_id = None
        self.last_seen = None
        self.last_frame = None
        self.last_box = None
        self.zone = None
        self.dwell = 0.0
        self.qualified = False
        self.offer = GENERAL.copy()
        self.offer_until = 0
        self.camera_active = False

    def event(self, kind, detail, zone=None):
        self.events.appendleft({"type": kind, "detail": detail, "zone": zone,
                                "timestamp": datetime.now(timezone.utc).isoformat()})

    def clear_dwell(self):
        self.zone, self.dwell, self.qualified = None, 0.0, False

    def general(self):
        self.offer, self.offer_until = GENERAL.copy(), 0

    def end_visit(self, reason):
        if self.session_id is not None:
            self.event("visit_ended", reason)
        self.session_id = None
        self.last_seen = self.last_box = None
        self.clear_dwell()
        self.general()

    def stop(self, reason="Camera stopped."):
        self.end_visit(reason)
        self.last_frame = None
        self.camera_active = False

    def expire(self, now):
        if self.last_frame is not None and now - self.last_frame > MAX_SAMPLE_GAP:
            self.clear_dwell()
        if self.last_seen is not None and now - self.last_seen > VISIT_GAP:
            self.end_visit("Visitor no longer visible; temporary ID discarded.")
        if self.last_frame is not None and now - self.last_frame > VISIT_GAP:
            self.camera_active = False
            self.general()

    def process(self, observation, result, now):
        self.expire(now)
        previous_frame = self.last_frame
        self.last_frame = now
        self.camera_active = True
        faces = result.get("faces", [])
        if len(faces) != 1:
            self.clear_dwell()
            self.general()
            # No attribution can be maintained safely when faces overlap.
            if len(faces) > 1:
                self.end_visit("Several faces visible; individual attribution suspended.")
            return self.snapshot(now)

        box = faces[0]["bbox"]
        if self.last_box:
            old_x, old_y, old_w, old_h = self.last_box
            x, y, w, h = box
            jump = math.hypot((x + w / 2) - (old_x + old_w / 2),
                              (y + h / 2) - (old_y + old_h / 2))
            if jump > max(old_w, old_h) * 0.8:
                self.end_visit("Face position changed abruptly; beginning a new temporary track.")
        if self.session_id is None:
            self.visits += 1
            self.session_id = f"Visit {self.visits:03d}"
            self.event("visit_started", f"{self.session_id}: temporary visual track, not a recognised person.")
        self.last_box = box
        self.last_seen = now

        zone = observation.get("zone")
        if zone not in OFFERS:
            self.clear_dwell()
            # Uncertain gaze must not leave a personalised-looking offer on screen.
            self.general()
            return self.snapshot(now)
        elapsed = 0 if previous_frame is None else now - previous_frame
        if self.zone != zone or elapsed > MAX_SAMPLE_GAP:
            self.zone, self.dwell, self.qualified = zone, 0.0, False
        else:
            self.dwell += max(0, elapsed)
            self.zone_totals[zone] += max(0, elapsed)
        if self.dwell >= self.config.dwell_threshold_s:
            if not self.qualified:
                self.event("zone_dwell", f"Estimated continuous gaze for {self.dwell:.1f}s.", zone)
                self.qualified = True
            if now >= self.offer_until and self.offer.get("zone") != zone:
                self.offer = OFFERS[zone].copy()
                self.offer_until = now + self.config.offer_hold_s
                self.event("offer_shown", "Example offer displayed after stable zone dwell; no purchase inferred.", zone)
        return self.snapshot(now)

    def snapshot(self, now):
        self.expire(now)
        return {"session_id": self.session_id, "current_zone": self.zone,
                "dwell_s": round(self.dwell, 2),
                "zone_totals": {z: round(v, 2) for z, v in self.zone_totals.items()},
                "offer": self.offer.copy(), "events": list(self.events),
                "visits": self.visits, "camera_active": self.camera_active,
                "updated_at": datetime.now(timezone.utc).isoformat()}
