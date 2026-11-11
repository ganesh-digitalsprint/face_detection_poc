from __future__ import annotations


class FaceMaskError(Exception):
    """Base class for expected, user-presentable errors."""

    status_code = 400


class ConfigError(FaceMaskError):
    """face_mask.yaml missing or invalid; raised at startup so the service fails fast."""

    status_code = 500


class NotFoundError(FaceMaskError):
    status_code = 404


class InvalidTransitionError(FaceMaskError):
    status_code = 409
