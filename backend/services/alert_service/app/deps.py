from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ProducerIdentity:
    use_case: str
    producer: str


@dataclass(frozen=True)
class OperatorIdentity:
    actor_id: str
    use_cases: tuple[str, ...]


def get_db(request: Request):
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def _bearer(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization[7:]


def get_producer(request: Request, authorization: str | None = Header(default=None)) -> ProducerIdentity:
    token = _bearer(authorization)
    credentials = request.app.state.settings.producer_credentials
    if not credentials:
        raise HTTPException(503, detail={"code": "AUTH_NOT_CONFIGURED", "message": "Producer authentication is not configured"})
    for secret, identity in credentials.items():
        if token and secrets.compare_digest(token, secret):
            return ProducerIdentity(str(identity["use_case"]), str(identity["producer"]))
    raise HTTPException(401, detail={"code": "UNAUTHENTICATED", "message": "Valid producer bearer token required"})


def get_operator(request: Request, authorization: str | None = Header(default=None)) -> OperatorIdentity:
    token = _bearer(authorization)
    credentials = request.app.state.settings.operator_credentials
    if not credentials:
        raise HTTPException(503, detail={"code": "AUTH_NOT_CONFIGURED", "message": "Operator authentication is not configured"})
    for secret, identity in credentials.items():
        if token and secrets.compare_digest(token, secret):
            scopes = tuple(str(v) for v in identity.get("use_cases", []))
            return OperatorIdentity(str(identity["actor_id"]), scopes)
    raise HTTPException(401, detail={"code": "UNAUTHENTICATED", "message": "Valid operator bearer token required"})


def require_scope(operator: OperatorIdentity, use_case: str) -> None:
    if "*" not in operator.use_cases and use_case not in operator.use_cases:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Operator is not authorized for this use case"})
