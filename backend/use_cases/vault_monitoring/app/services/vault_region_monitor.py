"""Entry-only confirmation on existing ByteTrack tracks. No detector or exit rules."""
from app.core.zones.vault_room_zone import point_in_polygon, reference_point
from math import hypot
from copy import deepcopy


class VaultRegionMonitor:
    def __init__(self, profile, *, max_gap_seconds=6, min_frames=2, person_seconds=1, tolerance=0.002):
        self.profile = deepcopy(profile)
        self.max_gap_seconds = max_gap_seconds
        self.min_frames = min_frames
        self.person_seconds = person_seconds
        self.tolerance = tolerance
        self.zones = {row["id"]: row for row in self.profile["zones"] if row.get("enabled", True)}
        self.reset()

    def reset(self):
        self.person_since = None
        self.person_ids = ()
        self.person_emitted = False
        self.vault_pending = {}
        self.vault_confirmed = set()
        self.last_time = None
        self.presence_pending = {}
        self.presence_confirmed = set()
        self.person_samples = 0
        self.vault_samples = {}
        self.vault_seen_outside = set()
        self.vault_entry_kind = {}

    def contains(self, x, y, polygon):
        if point_in_polygon(x, y, polygon):
            return True
        for a, b in zip(polygon, polygon[1:] + polygon[:1]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = dx * dx + dy * dy
            t = max(0, min(1, ((x-a[0])*dx + (y-a[1])*dy)/length)) if length else 0
            if hypot(x-a[0]-t*dx, y-a[1]-t*dy) <= self.tolerance:
                return True
        return False

    def inside(self, key, tracks):
        zone = self.zones.get(key)
        if not zone:
            return []
        result = []
        for track in tracks:
            x, y = reference_point((track["x"], track["y"], track["x"] + track["w"], track["y"] + track["h"]), zone.get("reference", "bottom_center"))
            if self.contains(x, y, zone["polygon"]):
                result.append(track)
        return result

    def count(self, tracks):
        return len(self.monitoring_tracks(tracks))

    def monitoring_tracks(self, tracks):
        # Counting and presence events must use exactly the same membership set.
        return self.inside('person_monitoring_roi', tracks) if 'person_monitoring_roi' in self.zones else list(tracks)

    def body_entry_diagnostics(self, now, tracks):
        zone=self.zones.get('vault_area_roi')
        result=[]
        for track in tracks:
            bbox=[track['x'],track['y'],track['x']+track['w'],track['y']+track['h']]
            point=reference_point(bbox,zone.get('reference','bottom_center')) if zone else None
            inside=self.contains(*point,zone['polygon']) if zone else False
            identifier=track['track_id'];since=self.vault_pending.get(identifier)
            result.append(dict(track_id=identifier,bbox=bbox,reference=zone.get('reference','bottom_center') if zone else None,
                point=point,polygon=zone['polygon'] if zone else None,inside=inside,
                samples=self.vault_samples.get(identifier,0),min_samples=self.min_frames,
                duration_seconds=now-since if since is not None else 0,
                confirmation_seconds=zone.get('confirmation_seconds',1) if zone else None,
                reason='REGION_NOT_ACTIVE' if not zone else 'BODY_REFERENCE_OUTSIDE' if not inside else
                    'ALREADY_CONFIRMED' if identifier in self.vault_confirmed else 'AWAITING_CONFIRMATION'))
        return result

    def update(self, now, tracks, stable_count):
        result = []
        if self.last_time is not None and now <= self.last_time:
            return result  # Retries/repeated source frames are not consecutive observations.
        if self.last_time is not None and now - self.last_time >= self.max_gap_seconds:
            self.person_since = None
            self.person_ids = ()
            self.vault_pending.clear()
            self.vault_confirmed.clear()
            self.vault_samples.clear()
            self.vault_seen_outside.clear()
            self.vault_entry_kind.clear()
            self.presence_pending.clear()
            self.presence_confirmed.clear()
            self.person_samples = 0
        self.last_time = now
        people = tuple(sorted(track["track_id"] for track in self.monitoring_tracks(tracks)))
        region = 'person_monitoring_roi' if 'person_monitoring_roi' in self.zones else None
        for identifier in set(self.presence_pending) - set(people):
            self.presence_pending.pop(identifier)
            self.presence_confirmed.discard(identifier)
        for identifier in people:
            since, samples = self.presence_pending.get(identifier, (now, 0))
            self.presence_pending[identifier] = (since, samples + 1)
            if identifier not in self.presence_confirmed and samples + 1 >= self.min_frames and now - since >= self.person_seconds:
                self.presence_confirmed.add(identifier)
                result.append(('PERSON_DETECTED', 'Person consistently detected in the monitoring area',
                    dict(region=region, track_id=identifier, count=len(people), membership_mode='roi' if region else 'full_frame')))
        if len(people) != 2 or people != self.person_ids:
            self.person_since = now if len(people) == 2 else None
            self.person_ids = people
            self.person_samples = 0
        self.person_samples += 1
        zone = self.zones.get("person_monitoring_roi", {})
        if stable_count == 2 and self.person_since is not None and not self.person_emitted \
                and self.person_samples >= self.min_frames \
                and now - self.person_since >= max(1.0, zone.get("confirmation_seconds", 1.0)):
            self.person_emitted = True
            result.append(("PERSON_ENTERED", "Two people confirmed in the Person Monitoring Area",
                dict(region=region, count=2, track_ids=list(people), detection_method='inferred_presence', membership_mode='roi' if region else 'full_frame',
                     verified_doorway_entry=False)))
        inside = {track["track_id"] for track in self.inside("vault_area_roi", tracks)}
        self.vault_seen_outside.update(track['track_id'] for track in tracks if track['track_id'] not in inside)
        for identifier in list(self.vault_pending):
            if identifier not in inside:
                self.vault_pending.pop(identifier)
                self.vault_confirmed.discard(identifier)
                self.vault_samples.pop(identifier, None)
                self.vault_entry_kind.pop(identifier, None)
        zone = self.zones.get("vault_area_roi")
        for identifier in inside:
            if identifier not in self.vault_pending:
                self.vault_pending[identifier] = now
                self.vault_entry_kind[identifier] = 'observed_entry' if identifier in self.vault_seen_outside else 'initial_occupancy'
            self.vault_samples[identifier] = self.vault_samples.get(identifier, 0) + 1
            if identifier not in self.vault_confirmed and self.vault_samples[identifier] >= self.min_frames and now - self.vault_pending[identifier] >= zone.get("confirmation_seconds", 1.0):
                self.vault_confirmed.add(identifier)
                kind = self.vault_entry_kind[identifier]
                result.append(("VAULT_AREA_ENTERED", 'Person entered the Vault Area' if kind == 'observed_entry'
                    else 'Initial Vault Area occupancy confirmed; entry was not observed',
                    dict(region="vault_area_roi", track_id=identifier, entry_kind=kind,
                         observed_entry=kind == 'observed_entry', initial_occupancy=kind == 'initial_occupancy',
                         reference=zone.get('reference', 'bottom_center'), confirmation_seconds=zone.get('confirmation_seconds', 1.0))))
        return result
