"""Liveness Test Lab: shared-feature refactor parity, diagnostics service and router."""


import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.liveness_config import LivenessChallenge, LivenessSettings, LivenessTestSettings
from app.ml.deepface_service import DetectedFaceInfo, MultipleFacesError, NoFaceDetectedError
from app.services import liveness_features as features_mod
from app.services import liveness_service
from app.services.liveness_features import ActionState, FaceFeatures, apply_action_hits, evaluate_action
from app.services.liveness_test_service import (
    LivenessTestService,
    LivenessTestSessionNotFoundError,
    get_liveness_test_service,
)
from app.utils.image import BoundingBox

ALL = [c for c in LivenessChallenge]


def _config(hold_ms=0):
    return LivenessSettings(
        directional_challenges={"hold_duration_ms": hold_ms},
        available_challenges=ALL,
        challenge_count=1,
    )


def _features(yaw=0.0, pitch=0.0, smile=0.6, eye=10.0):
    return FaceFeatures(0.5, 0.5, yaw, pitch, smile, eye)


# ---------------------------------------------------------------- refactor parity
def test_vault_service_uses_the_shared_functions_and_constants():
    assert liveness_service.extract_features is features_mod.extract_features
    assert liveness_service.evaluate_action is features_mod.evaluate_action
    assert liveness_service.FRONTAL_YAW_MAX == 0.07
    assert liveness_service.FRONTAL_PITCH_MAX == 0.06
    assert liveness_service.REQUIRED_ACTION_HITS == 2
    assert liveness_service.CROSS_AXIS_LIMIT == 0.6


@pytest.mark.parametrize(
    ("challenge", "move", "passes"),
    [
        (LivenessChallenge.TURN_LEFT, {"yaw": 0.13}, True),
        (LivenessChallenge.TURN_LEFT, {"yaw": 0.11}, False),
        (LivenessChallenge.TURN_LEFT, {"yaw": -0.13}, False),  # wrong way never passes
        (LivenessChallenge.TURN_RIGHT, {"yaw": -0.13}, True),
        (LivenessChallenge.TURN_RIGHT, {"yaw": -0.11}, False),
        (LivenessChallenge.LOOK_UP, {"pitch": -0.10}, True),
        (LivenessChallenge.LOOK_UP, {"pitch": -0.08}, False),
        (LivenessChallenge.LOOK_DOWN, {"pitch": 0.10}, True),
        (LivenessChallenge.LOOK_DOWN, {"pitch": 0.08}, False),
        (LivenessChallenge.TURN_LEFT, {"yaw": 0.13, "pitch": 0.08}, False),  # cross-axis drift
        (LivenessChallenge.SMILE, {"smile": 0.71}, True),
        (LivenessChallenge.SMILE, {"smile": 0.69}, False),
    ],
)
def test_production_thresholds_per_challenge(challenge, move, passes):
    state = ActionState(baseline=_features())
    current = _features(**move)
    config = _config()
    outcome = False
    # Smile needs REQUIRED_ACTION_HITS consecutive frames; directional uses the (0 ms) hold.
    for _ in range(features_mod.REQUIRED_ACTION_HITS):
        passed, _score, reason, _fb = evaluate_action(state, challenge, current, config)
        outcome, _ = apply_action_hits(state, challenge, passed, reason)
    assert outcome is passes


def test_smile_needs_consecutive_hits():
    state = ActionState(baseline=_features())
    passed, _s, reason, _f = evaluate_action(state, LivenessChallenge.SMILE, _features(smile=0.8), _config())
    assert apply_action_hits(state, LivenessChallenge.SMILE, passed, reason) == (False, "Hold that position")


# ---------------------------------------------------------------- service
class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class _Raises:
    def __init__(self, exc):
        self.exc = exc

    def detect(self, image, *, max_side=None):
        raise self.exc

    def detect_single_face(self, image, *, max_side=None, require_landmarks=False):
        raise self.exc


class _Faces:
    """Returns a face whose nose moves by `nose_dx` on every call after the first two."""

    def __init__(self, nose_dx=0):
        self.calls = 0
        self.nose_dx = nose_dx

    def _face(self):
        self.calls += 1
        dx = self.nose_dx if self.calls > 2 else 0
        return DetectedFaceInfo(
            bbox=BoundingBox(200, 100, 240, 260), detection_confidence=1.0,
            landmarks={"left_eye": (280, 190), "right_eye": (360, 190), "nose": (320 + dx, 240),
                       "mouth_left": (290, 300), "mouth_right": (350, 300)},
        )

    def detect(self, image, *, max_side=None):
        return self._face()

    def detect_single_face(self, image, *, max_side=None, require_landmarks=False):
        return self._face()


def _service(landmarker=None, detection=None, clock=None, **test_cfg):
    return LivenessTestService(
        liveness_config=_config(), test_config=LivenessTestSettings(**test_cfg),
        landmarker=landmarker or _Faces(), detection=detection or _Faces(), clock=clock or _Clock(),
    )


def _textured(height=480, width=640, value=128):
    rng = np.random.default_rng(0)
    noise = rng.integers(-60, 60, (height, width, 1))
    return np.clip(value + noise, 0, 255).astype(np.uint8).repeat(3, axis=2)


def _reason(service, image):
    session_id = service.start_session()
    return service.analyze(session_id, image).results[0]


def test_black_image_reports_too_dark():
    result = _reason(_service(landmarker=_Raises(NoFaceDetectedError("none"))), np.zeros((480, 640, 3), np.uint8))
    assert (result.visible, result.not_visible_reason) == (False, "TOO_DARK")


def test_blurred_image_reports_blurry():
    blurred = cv2.GaussianBlur(_textured(), (0, 0), 12)
    result = _reason(_service(landmarker=_Raises(NoFaceDetectedError("none"))), blurred)
    assert result.not_visible_reason == "BLURRY"


def test_sharp_well_lit_image_without_face_reports_no_face():
    result = _reason(_service(landmarker=_Raises(NoFaceDetectedError("none"))), _textured())
    assert result.not_visible_reason == "NO_FACE"


def test_multiple_faces_reported():
    result = _reason(_service(landmarker=_Raises(MultipleFacesError(2))), _textured())
    assert result.not_visible_reason == "MULTIPLE_FACES"


def test_one_failing_detector_does_not_fail_compare_mode():
    service = _service(detection=_Raises(RuntimeError("model missing")))
    analysis = service.analyze(service.start_session(), _textured(), detector="both")
    mediapipe, deepface = analysis.results
    assert mediapipe.visible and mediapipe.error is None
    assert deepface.visible is False and "deepface detection failed" in deepface.error
    assert "model missing" not in deepface.error  # no internal detail leaks


def test_face_analysis_builds_baseline_and_passes_turn_left():
    # +x nose movement = subject's physical left in an un-mirrored frame.
    service = _service(landmarker=_Faces(nose_dx=12))
    session_id = service.start_session()
    service.set_challenge(session_id, "TURN_LEFT")
    frames = [service.analyze(session_id, _textured()) for _ in range(3)]
    assert frames[0].baseline_ready is False
    assert frames[1].baseline_ready is True
    last = frames[2]
    result = last.results[0]
    assert result.landmarks["nose"].x == 332  # original image pixel space
    assert (last.image_width, last.image_height) == (640, 480)
    assert result.pose.direction == "TURNED_LEFT"
    assert result.pose.yaw_delta == pytest.approx(0.15)
    assert last.challenge.passed is True
    assert last.challenge.threshold == pytest.approx(0.12)
    assert last.thresholds.yaw_pass == pytest.approx(0.12)


def test_reset_baseline_recalibrates():
    service = _service()
    session_id = service.start_session()
    service.analyze(session_id, _textured())
    assert service.analyze(session_id, _textured()).baseline_ready is True
    service.reset_baseline(session_id)
    assert service.analyze(session_id, _textured()).baseline_ready is False


def test_session_ttl_expires():
    clock = _Clock()
    service = _service(clock=clock, session_ttl_seconds=600)
    session_id = service.start_session()
    clock.now += 601
    with pytest.raises(LivenessTestSessionNotFoundError):
        service.analyze(session_id, _textured())


def test_session_cap_evicts_oldest():
    clock = _Clock()
    service = _service(clock=clock, max_sessions=20)
    ids = []
    for _ in range(21):
        clock.now += 1
        ids.append(service.start_session())
    with pytest.raises(LivenessTestSessionNotFoundError):
        service.reset_baseline(ids[0])
    service.reset_baseline(ids[-1])  # newest is still there


# ---------------------------------------------------------------- router
@pytest.fixture
def client(monkeypatch):
    from app.main import create_app

    monkeypatch.setattr(settings, "LIVENESS_TEST_ENABLED", True)
    app = create_app()
    app.dependency_overrides[get_liveness_test_service] = lambda: _SERVICE
    return TestClient(app)


_SERVICE = _service()


def test_disabled_flag_returns_404(monkeypatch):
    from app.main import create_app

    monkeypatch.setattr(settings, "LIVENESS_TEST_ENABLED", False)
    response = TestClient(create_app()).get("/api/v1/liveness-test/config")
    assert response.status_code == 404


def test_flag_switched_off_after_mount_still_404(client, monkeypatch):
    monkeypatch.setattr(settings, "LIVENESS_TEST_ENABLED", False)
    assert client.post("/api/v1/liveness-test/sessions").status_code == 404


def test_unknown_session_404(client):
    _ok, jpeg = cv2.imencode(".jpg", _textured())
    response = client.post("/api/v1/liveness-test/sessions/nope/analyze",
                           files={"frame": ("f.jpg", jpeg.tobytes(), "image/jpeg")})
    assert response.status_code == 404


def test_oversized_upload_413(client):
    session_id = client.post("/api/v1/liveness-test/sessions").json()["session_id"]
    big = b"\xff\xd8" + b"0" * (2 * 1024 * 1024 + 10)
    response = client.post(f"/api/v1/liveness-test/sessions/{session_id}/analyze",
                           files={"frame": ("f.jpg", big, "image/jpeg")})
    assert response.status_code == 413


def test_end_to_end_analyze_and_delete(client):
    created = client.post("/api/v1/liveness-test/sessions")
    assert created.status_code == 201
    session_id = created.json()["session_id"]
    _ok, jpeg = cv2.imencode(".jpg", _textured())
    response = client.post(f"/api/v1/liveness-test/sessions/{session_id}/analyze",
                           files={"frame": ("f.jpg", jpeg.tobytes(), "image/jpeg")},
                           data={"detector": "mediapipe", "challenge": "TURN_RIGHT"})
    assert response.status_code == 200
    body = response.json()
    assert body["session_id_prefix"] == session_id[:8] and body["results"][0]["visible"] is True
    assert client.post(f"/api/v1/liveness-test/sessions/{session_id}/challenge", json={"challenge": None}).status_code == 200
    assert client.delete(f"/api/v1/liveness-test/sessions/{session_id}").status_code == 200
    assert client.delete(f"/api/v1/liveness-test/sessions/{session_id}").status_code == 404
