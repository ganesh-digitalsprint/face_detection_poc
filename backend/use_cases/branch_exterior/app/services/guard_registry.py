from __future__ import annotations

import logging

from app.core.paths import BACKEND_ROOT
from app.db.repositories.interfaces import Repositories
from app.services.detection.face_recognizer import GuardFaceRecognizer

logger = logging.getLogger(__name__)

recognizer = GuardFaceRecognizer()


async def retrain(repos: Repositories) -> int:
    guards = await repos.guards.list()
    payload = [
        (g.id, g.name, [str(BACKEND_ROOT / p) for p in g.photo_paths])
        for g in guards
        if g.active and g.photo_paths
    ]
    count = recognizer.train(payload)
    logger.info("Guard recognizer retrained on %d face image(s) across %d guard(s)", count, len(payload))
    return count
