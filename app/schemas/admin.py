from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.common import AppRole


class EmployeeRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AppRole


class AdminEmployee(BaseModel):
    id: UUID
    full_name: str
    email: str
    role: AppRole
    manager_id: UUID | None = None


class EmployeeRoleResult(BaseModel):
    employee_id: UUID
    previous_role: AppRole
    role: AppRole

