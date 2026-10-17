from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import AppRole


class ManagerSummary(BaseModel):
    id: str
    full_name: str


class CourseSummary(BaseModel):
    id: str
    title: str
    description: str
    duration_minutes: int


class AssignedCourse(BaseModel):
    id: str
    course_id: str
    employee_id: str
    status: Literal["not_started", "in_progress", "completed"]
    progress_percent: int = Field(ge=0, le=100)
    score_percent: float | None = Field(default=None, ge=0, le=100)
    assigned_by: str | None = None
    assigned_at: datetime
    completed_at: datetime | None = None
    course: CourseSummary | None = None


class ProfileNotification(BaseModel):
    id: str
    employee_id: str
    request_id: str | None = None
    notification_type: str
    title: str
    body: str
    read_at: datetime | None = None
    created_at: datetime


class EmployeeDashboard(BaseModel):
    """Current employee's personal cabinet; only explicitly listed fields are public."""

    id: str
    employee_code: str
    full_name: str
    email: str
    company: str
    job_title: str
    department: str
    manager_id: str | None = None
    hired_at: date
    vacation_days_remaining: float = Field(ge=0)
    role: AppRole
    external_source: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    manager: ManagerSummary | None = None
    assigned_courses: list[AssignedCourse] = Field(default_factory=list)
    notifications: list[ProfileNotification] = Field(default_factory=list)
