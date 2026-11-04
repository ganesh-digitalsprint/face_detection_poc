from app.db.models import CameraSource, CameraUseCaseAssignment, RegistryCamera, RegistryLocation, RegistryZone, VaultRoomSession
from app.db.database import Base


def test_registry_models_register_common_tables_and_assignment_scoped_zone_keys():
    expected = {
        "registry_locations", "registry_cameras", "camera_sources",
        "camera_use_case_assignments", "registry_zones",
    }
    assert expected <= set(Base.metadata.tables)
    zone_constraints = {constraint.name for constraint in RegistryZone.__table__.constraints}
    assert "uq_registry_zones_assignment_key" in zone_constraints
    assert any(column.name == "assignment_id" for column in RegistryZone.__table__.columns)
    assert any(column.name == "zones_version" for column in CameraUseCaseAssignment.__table__.columns)
    assert "fingerprint" in CameraSource.__table__.columns
    assert "location_id" in RegistryCamera.__table__.columns
    assert "code" in RegistryLocation.__table__.columns


def test_vault_room_session_has_nullable_registry_identity_columns():
    for field in ("location_id", "camera_id", "assignment_id"):
        assert field in VaultRoomSession.__table__.columns
        assert VaultRoomSession.__table__.columns[field].nullable is True
