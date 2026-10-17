from typing import Literal

from pydantic import BaseModel

AppRole = Literal["worker", "manager", "director", "hr_admin"]


class UserContext(BaseModel):
    id: str
    auth_user_id: str
    role: AppRole
    manager_id: str | None = None
