"""Responses for the multi-factor PGM vault authentication flow."""

from pydantic import BaseModel, Field


class LivenessDecision(BaseModel):
    passed: bool
    challenge: str
    score: float
    status: str
    reason: str
    completed_challenges: int
    required_challenges: int
    # Coarse UI feedback (DETECTING | HOLDING | WRONG_DIRECTION); never raw pose values.
    feedback: str | None = None


class RecognitionDecision(BaseModel):
    matched: bool
    employee_id: str | None = None
    # Internal only: face distance is never serialized to the client.
    distance: float | None = Field(default=None, exclude=True)


class AuthorizationDecision(BaseModel):
    active: bool


class CustodianSummary(BaseModel):
    """Display-only record of a custodian the dual-control session accepted."""

    slot: int
    employee_id: str
    name: str
    department: str | None = None
    designation: str | None = None
    verified_at: str  # ISO 8601 UTC
    authorization_active: bool = True


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
    handoff_remaining_seconds: int = 0
    authenticated_custodians: list[CustodianSummary] = Field(default_factory=list)


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
