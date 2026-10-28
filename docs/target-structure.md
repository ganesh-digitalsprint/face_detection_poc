# FedBank

## Project Structure

```
fedbank/
│
├── README.md
├── .env.example
├── .gitignore
├── docker-compose.yml
├── docker-compose.dev.yml
│
├── config/
│   ├── app.yaml
│   ├── database.yaml
│   ├── models.yaml
│   ├── alerts.yaml
│   ├── evidence.yaml
│   ├── branches.yaml
│   │
│   └── use_cases/
│       ├── vault_monitoring.yaml
│       └── branch_exterior.yaml
│
├── data/                              # Runtime data; never commit
│   ├── uploads/
│   ├── evidence/
│   ├── temporary/
│   └── model_weights/
│
├── docker/
│   └── postgres/
│       └── init.sql                   # Optional initial setup only
│
├── backend/
│   ├── README.md
│   ├── pyproject.toml                 # Shared tooling/configuration
│   │
│   ├── shared/
│   │   └── fedbank_core/
│   │       ├── __init__.py
│   │       ├── config/
│   │       │   ├── __init__.py
│   │       │   └── loader.py
│   │       ├── database/
│   │       │   ├── __init__.py
│   │       │   └── base.py
│   │       ├── security/
│   │       │   ├── __init__.py
│   │       │   └── auth.py
│   │       ├── events/
│   │       │   ├── __init__.py
│   │       │   └── schemas.py
│   │       ├── logging.py
│   │       └── exceptions.py
│   │
│   ├── services/
│   │   ├── alert_service/
│   │   │   ├── app/
│   │   │   │   ├── main.py
│   │   │   │   ├── settings.py
│   │   │   │   ├── api/
│   │   │   │   │   └── routes/
│   │   │   │   │       ├── health.py
│   │   │   │   │       ├── alerts.py
│   │   │   │   │       └── incidents.py
│   │   │   │   ├── db/
│   │   │   │   │   ├── models.py
│   │   │   │   │   └── repositories.py
│   │   │   │   ├── schemas/
│   │   │   │   │   ├── alert.py
│   │   │   │   │   └── incident.py
│   │   │   │   └── services/
│   │   │   │       ├── alert_manager.py
│   │   │   │       └── incident_manager.py
│   │   │   ├── tests/
│   │   │   ├── Dockerfile
│   │   │   └── requirements.txt
│   │   │
│   │   ├── evidence_service/
│   │   │   ├── app/
│   │   │   │   ├── main.py
│   │   │   │   ├── settings.py
│   │   │   │   ├── api/routes/
│   │   │   │   │   ├── health.py
│   │   │   │   │   └── evidence.py
│   │   │   │   ├── db/
│   │   │   │   │   ├── models.py
│   │   │   │   │   └── repositories.py
│   │   │   │   ├── schemas/
│   │   │   │   │   └── evidence.py
│   │   │   │   └── services/
│   │   │   │       ├── evidence_manager.py
│   │   │   │       └── storage_provider.py
│   │   │   ├── tests/
│   │   │   ├── Dockerfile
│   │   │   └── requirements.txt
│   │   │
│   │   └── stream_service/            # Keep separate if independently needed
│   │       ├── app/
│   │       │   ├── main.py
│   │       │   ├── settings.py
│   │       │   ├── api/routes/
│   │       │   │   ├── health.py
│   │       │   │   └── streams.py
│   │       │   ├── schemas/
│   │       │   │   └── stream.py
│   │       │   └── services/
│   │       │       ├── stream_manager.py
│   │       │       └── camera_reader.py
│   │       ├── tests/
│   │       ├── Dockerfile
│   │       └── requirements.txt
│   │
│   └── use_cases/
│       │
│       ├── vault_monitoring/
│       │   ├── README.md
│       │   ├── Dockerfile
│       │   ├── requirements.txt
│       │   ├── alembic.ini
│       │   │
│       │   ├── app/
│       │   │   ├── __init__.py
│       │   │   ├── main.py
│       │   │   ├── settings.py
│       │   │   ├── deps.py
│       │   │   │
│       │   │   ├── api/
│       │   │   │   ├── __init__.py
│       │   │   │   ├── router.py
│       │   │   │   ├── errors.py
│       │   │   │   └── routes/
│       │   │   │       ├── __init__.py
│       │   │   │       ├── health.py
│       │   │   │       ├── employees.py
│       │   │   │       ├── authorization.py
│       │   │   │       ├── registration.py
│       │   │   │       ├── detection.py
│       │   │   │       ├── recognition.py
│       │   │   │       ├── verification.py
│       │   │   │       ├── liveness.py
│       │   │   │       ├── access.py
│       │   │   │       ├── sessions.py
│       │   │   │       ├── monitoring.py
│       │   │   │       └── streams.py
│       │   │   │
│       │   │   ├── core/
│       │   │   │   ├── config.py
│       │   │   │   ├── logging.py
│       │   │   │   ├── security.py
│       │   │   │   └── exceptions.py
│       │   │   │
│       │   │   ├── db/
│       │   │   │   ├── database.py
│       │   │   │   ├── models/
│       │   │   │   │   ├── employee.py
│       │   │   │   │   ├── authorization.py
│       │   │   │   │   ├── access_session.py
│       │   │   │   │   └── audit_log.py
│       │   │   │   ├── repositories/
│       │   │   │   │   ├── employee_repository.py
│       │   │   │   │   ├── authorization_repository.py
│       │   │   │   │   ├── session_repository.py
│       │   │   │   │   └── audit_repository.py
│       │   │   │   └── unit_of_work.py
│       │   │   │
│       │   │   ├── schemas/
│       │   │   │   ├── employee.py
│       │   │   │   ├── authorization.py
│       │   │   │   ├── face.py
│       │   │   │   ├── recognition.py
│       │   │   │   ├── liveness.py
│       │   │   │   ├── access.py
│       │   │   │   ├── session.py
│       │   │   │   ├── monitoring.py
│       │   │   │   └── common.py
│       │   │   │
│       │   │   ├── services/
│       │   │   │   ├── authorization_registration.py
│       │   │   │   ├── employee_service.py
│       │   │   │   ├── registration_service.py
│       │   │   │   ├── recognition_service.py
│       │   │   │   ├── liveness_service.py
│       │   │   │   ├── access_service.py
│       │   │   │   ├── session_service.py
│       │   │   │   ├── monitoring_service.py
│       │   │   │   ├── alert_client.py
│       │   │   │   ├── evidence_client.py
│       │   │   │   └── stream_client.py
│       │   │   │
│       │   │   ├── ml/
│       │   │   │   ├── face_detection.py
│       │   │   │   ├── face_embedding.py
│       │   │   │   ├── face_recognition.py
│       │   │   │   ├── liveness_model.py
│       │   │   │   └── deepface_service.py
│       │   │   │
│       │   │   ├── clients/
│       │   │   │   ├── qdrant_client.py
│       │   │   │   ├── alert_client.py
│       │   │   │   └── evidence_client.py
│       │   │   │
│       │   │   └── utils/
│       │   │       ├── image.py
│       │   │       ├── similarity.py
│       │   │       ├── validation.py
│       │   │       └── time.py
│       │   │
│       │   ├── migrations/
│       │   └── tests/
│       │       ├── unit/
│       │       ├── integration/
│       │       └── api/
│       │
│       └── branch_exterior/
│           ├── README.md
│           ├── Dockerfile
│           ├── requirements.txt
│           ├── alembic.ini
│           │
│           ├── app/
│           │   ├── __init__.py
│           │   ├── main.py
│           │   ├── settings.py
│           │   ├── deps.py
│           │   │
│           │   ├── api/
│           │   │   ├── router.py
│           │   │   ├── errors.py
│           │   │   └── routes/
│           │   │       ├── health.py
│           │   │       ├── cameras.py
│           │   │       ├── streams.py
│           │   │       ├── detection.py
│           │   │       ├── tracking.py
│           │   │       ├── zones.py
│           │   │       ├── analytics.py
│           │   │       └── monitoring.py
│           │   │
│           │   ├── core/
│           │   │   ├── config.py
│           │   │   ├── logging.py
│           │   │   └── exceptions.py
│           │   │
│           │   ├── db/
│           │   │   ├── database.py
│           │   │   ├── models/
│           │   │   │   ├── camera.py
│           │   │   │   ├── zone.py
│           │   │   │   ├── incident.py
│           │   │   │   └── analytics_event.py
│           │   │   ├── repositories/
│           │   │   │   ├── camera_repository.py
│           │   │   │   ├── zone_repository.py
│           │   │   │   ├── incident_repository.py
│           │   │   │   └── analytics_repository.py
│           │   │   └── unit_of_work.py
│           │   │
│           │   ├── schemas/
│           │   │   ├── camera.py
│           │   │   ├── stream.py
│           │   │   ├── detection.py
│           │   │   ├── tracking.py
│           │   │   ├── zone.py
│           │   │   ├── analytics.py
│           │   │   └── monitoring.py
│           │   │
│           │   ├── services/
│           │   │   ├── camera_manager.py
│           │   │   ├── stream_worker.py
│           │   │   ├── detection_service.py
│           │   │   ├── tracking_service.py
│           │   │   ├── zone_service.py
│           │   │   ├── analytics_service.py
│           │   │   ├── loitering_service.py
│           │   │   ├── gathering_service.py
│           │   │   ├── movement_service.py
│           │   │   ├── after_hours_service.py
│           │   │   ├── alert_client.py
│           │   │   └── evidence_client.py
│           │   │
│           │   ├── ml/
│           │   │   ├── person_detection.py
│           │   │   ├── face_detection.py
│           │   │   ├── pose_estimation.py
│           │   │   └── model_loader.py
│           │   │
│           │   └── utils/
│           │       ├── frame.py
│           │       ├── image.py
│           │       ├── geometry.py
│           │       ├── timestamps.py
│           │       └── validation.py
│           │
│           ├── migrations/
│           └── tests/
│               ├── unit/
│               ├── integration/
│               └── api/
│
└── frontend/
    ├── package.json
    ├── vite.config.js
    ├── Dockerfile
    ├── nginx.conf
    └── src/
        ├── main.jsx
        ├── App.jsx
        ├── app/
        │   ├── router.jsx
        │   └── layouts/
        │       └── MainLayout.jsx
        ├── shared/
        │   ├── api/
        │   │   ├── client.js
        │   │   ├── alerts.js
        │   │   └── evidence.js
        │   ├── components/
        │   ├── hooks/
        │   └── utils/
        ├── pages/
        │   ├── Dashboard.jsx
        │   ├── Alerts.jsx
        │   ├── Incidents.jsx
        │   ├── Evidence.jsx
        │   └── Branches.jsx
        └── use-cases/
            ├── registry.js
            ├── vault-monitoring/
            │   ├── api/
            │   ├── hooks/
            │   ├── components/
            │   └── pages/
            │       ├── VaultDashboard.jsx
            │       ├── AccessSessions.jsx
            │       ├── FaceRegistration.jsx
            │       └── LiveMonitoring.jsx
            └── branch-exterior/
                ├── api/
                ├── hooks/
                ├── components/
                └── pages/
                    ├── ExteriorDashboard.jsx
                    ├── CameraWall.jsx
                    ├── ZoneManagement.jsx
                    └── DailyBrief.jsx
```
