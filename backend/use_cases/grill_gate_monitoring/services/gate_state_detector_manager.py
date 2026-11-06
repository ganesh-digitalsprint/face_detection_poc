"""Lifecycle manager for per-camera Grill Gate gate-state consumers."""
from __future__ import annotations

import threading
from collections.abc import Callable

from grill_gate_monitoring.services.frame_source import LiveCameraFrameSource
from grill_gate_monitoring.services.gate_state_detector import GrillGateStateDetector


class DetectorCapacityError(RuntimeError): pass
class DetectorConflictError(RuntimeError): pass
class DetectorManagerClosingError(RuntimeError): pass


class GrillGateStateDetectorManager:
    """Owns at most one detector per camera and stays within the capture worker cap."""

    def __init__(self, *, max_workers: int, worker_manager, config_loader_factory: Callable,
                 detector_options: dict | None = None, frame_processor_factory: Callable | None = None):
        self._max_workers = int(max_workers)
        if not 1 <= self._max_workers <= 4:
            raise ValueError("max_workers must be between 1 and 4")
        if worker_manager is None or config_loader_factory is None:
            raise ValueError("worker_manager and config_loader_factory are required")
        self._workers = worker_manager
        self._config_loader_factory = config_loader_factory
        self._detector_options = detector_options or {}
        self._frame_processor_factory = frame_processor_factory
        self._detectors: dict[str, GrillGateStateDetector] = {}
        self._lock = threading.RLock()
        self._closing = False

    def start_accepting(self) -> None:
        with self._lock:
            self._closing = False

    def start(self, camera_id: str, assignment_id: str) -> dict:
        camera, assignment = str(camera_id), str(assignment_id)
        with self._lock:
            if self._closing:
                raise DetectorManagerClosingError("Gate-state detector manager is shutting down")
            current = self._detectors.get(camera)
            if current is not None and current._thread.is_alive():
                if current.assignment_id != assignment:
                    raise DetectorConflictError("This camera already has a gate-state detector for another assignment")
                return current.status()
            if current is not None:
                current.stop()
                self._detectors.pop(camera, None)
            if sum(detector._thread.is_alive() for detector in self._detectors.values()) >= self._max_workers:
                raise DetectorCapacityError("The Grill Gate detector limit has been reached")

            subscription = LiveCameraFrameSource(self._workers.subscribe(camera, "gate-state"))
            detector = GrillGateStateDetector(
                camera, assignment, subscription,
                self._config_loader_factory(assignment), **self._detector_options,
                frame_processor=(self._frame_processor_factory(camera, assignment)
                                 if self._frame_processor_factory else None),
            )
            self._detectors[camera] = detector
            detector.start()
            return detector.status()

    def stop(self, camera_id: str, assignment_id: str) -> dict:
        camera, assignment = str(camera_id), str(assignment_id)
        with self._lock:
            detector = self._detectors.get(camera)
            if detector is None:
                return {"camera_id": camera, "assignment_id": assignment, "state": "UNKNOWN", "error": "detector not running"}
            if detector.assignment_id != assignment:
                raise DetectorConflictError("This camera's gate-state detector belongs to another assignment")
            self._detectors.pop(camera, None)
        detector.stop()
        return detector.status()

    def stop_all(self) -> None:
        with self._lock:
            self._closing = True
            detectors = list(self._detectors.values())
            self._detectors.clear()
        for detector in detectors:
            detector.stop()

    def status(self, assignment_id: str) -> dict | None:
        with self._lock:
            detector = next((item for item in self._detectors.values() if item.assignment_id == str(assignment_id)), None)
        return detector.status() if detector is not None and detector._thread.is_alive() else None

    def statuses(self) -> list[dict]:
        with self._lock:
            detectors = list(self._detectors.values())
        return [detector.status() for detector in detectors if detector._thread.is_alive()]

    def mesh_status(self, assignment_id: str) -> dict | None:
        with self._lock:
            detector = next((item for item in self._detectors.values()
                             if item.assignment_id == str(assignment_id)), None)
        if detector is None or not detector._thread.is_alive():
            return None
        return detector.mesh_status()


