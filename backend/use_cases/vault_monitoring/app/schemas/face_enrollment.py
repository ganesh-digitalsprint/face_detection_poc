"""Employee face enrollment response schema."""

from pydantic import BaseModel


class FaceEnrollmentResponse(BaseModel):
    message: str
    employee_id: str
    face_registered: bool
    images_enrolled: int
