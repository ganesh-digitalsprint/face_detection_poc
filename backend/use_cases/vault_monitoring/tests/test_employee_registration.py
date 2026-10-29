"""API tests for employee identity and separate vault authorization records."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.db.database import Base
from app.api.errors import install_error_handlers
from app.api.routes.employees import employee_router


@pytest.fixture
def client():
    test_app = FastAPI()
    install_error_handlers(test_app)
    test_app.include_router(employee_router)
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        def override_get_db():
            yield session

        test_app.dependency_overrides[get_db] = override_get_db
        with TestClient(test_app) as test_client:
            yield test_client
        test_app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def test_employee_create_and_duplicate_conflict(client):
    response = client.post(
        "/api/v1/employees",
        json={
            "employee_id": "EMP001",
            "name": "Ada Employee",
            "department": "Research",
            "designation": "Engineer",
        },
    )
    assert response.status_code == 201
    result = response.json()
    assert result["employee_id"] == "EMP001"
    assert result["name"] == "Ada Employee"
    assert result["id"]
    assert result["created_at"] and result["updated_at"]

    duplicate = client.post(
        "/api/v1/employees", json={"employee_id": "EMP001", "name": "Other"}
    )
    assert duplicate.status_code == 409


def test_employee_request_validation(client):
    response = client.post("/api/v1/employees", json={"employee_id": "EMP003"})
    assert response.status_code == 422


def test_employee_optional_fields_and_server_fields(client):
    response = client.post(
        "/api/v1/employees",
        json={"employee_id": " EMP004 ", "name": " Grace Hopper "},
    )
    assert response.status_code == 201
    result = response.json()
    assert result["employee_id"] == "EMP004"
    assert result["name"] == "Grace Hopper"
    assert result["department"] is None
    assert result["designation"] is None

    invalid = client.post(
        "/api/v1/employees",
        json={"employee_id": "EMP005", "name": "Ada", "id": 99},
    )
    assert invalid.status_code == 422


def test_authorization_requires_existing_employee(client):
    response = client.post(
        "/api/v1/employees/EMP404/authorization", json={}
    )
    assert response.status_code == 404


def test_authorization_defaults_inactive_and_rejects_duplicates(client):
    employee = client.post(
        "/api/v1/employees", json={"employee_id": "EMP101", "name": "Employee"}
    )
    assert employee.status_code == 201

    response = client.post("/api/v1/employees/EMP101/authorization", json={})
    assert response.status_code == 201
    result = response.json()
    assert result["employee_id"] == "EMP101"
    assert result["is_active"] is False
    assert "authorization_expires_at" not in result
    assert result["authorized_at"] is None
    assert result["face_registered"] is False

    duplicate = client.post("/api/v1/employees/EMP101/authorization", json={})
    assert duplicate.status_code == 409


def test_active_authorization_without_expiration_does_not_change_face_state(client):
    assert client.post(
        "/api/v1/employees", json={"employee_id": "EMP102", "name": "Employee"}
    ).status_code == 201
    response = client.post(
        "/api/v1/employees/EMP102/authorization",
        json={
            "is_active": True,
            "authorization_reason": "Vault access",
            "authorized_by": "ADMIN001",
            "remarks": "Authorized for vault operations",
        },
    )
    assert response.status_code == 201
    result = response.json()
    assert result["is_active"] is True
    assert result["authorized_at"] is not None
    assert "authorization_expires_at" not in result
    assert result["face_registered"] is False


def test_authorization_rejects_invalid_status_and_face_field(client):
    assert client.post(
        "/api/v1/employees", json={"employee_id": "EMP103", "name": "Employee"}
    ).status_code == 201

    invalid_status = client.post(
        "/api/v1/employees/EMP103/authorization",
        json={"is_active": "not-a-boolean"},
    )
    assert invalid_status.status_code == 422

    face_field = client.post(
        "/api/v1/employees/EMP103/authorization",
        json={"face_registered": True},
    )
    assert face_field.status_code == 422

    expiration_field = client.post(
        "/api/v1/employees/EMP103/authorization",
        json={"authorization_expires_at": "2027-10-05T18:30:00Z"},
    )
    assert expiration_field.status_code == 422
