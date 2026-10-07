"""Responses for the multi-factor PGM vault authentication flow."""

from pydantic import BaseModel


class LivenessDecision(BaseModel):
    passed: bool
    challenge: str
    score: float
    status: str
    reason: str
    completed_challenges: int
    required_challenges: int


class RecognitionDecision(BaseModel):
    matched: bool
    employee_id: str | None = None
    distance: float | None = None


class AuthorizationDecision(BaseModel):
    active: bool


class VaultAuthenticationResponse(BaseModel):
    liveness: LivenessDecision
    recognition: RecognitionDecision | None = None
    authorization: AuthorizationDecision | None = None
    access_granted: bool = False
    reason: str | None = None
    status: str = "DENIED"
    authenticated_count: int = 0
    required_count: int = 2
    remaining_seconds: int = 0
    next_challenge: str | None = None


class LivenessSessionResponse(BaseModel):
    session_id: str
    challenge: str
    expires_in_seconds: int
    status: str = "WAITING_FOR_FIRST_PERSON"
    required_persons: int = 2
    authenticated_count: int = 0
    started_at: str | None = None
    expires_at: str | None = None
    remaining_seconds: int = 180
