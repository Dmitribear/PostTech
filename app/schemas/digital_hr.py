from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

RequestType = Literal["leave", "advance"]
RequestStatus = Literal["pending", "approved", "rejected", "cancelled"]


class RequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_type: RequestType
    start_date: date | None = None
    end_date: date | None = None
    amount: float | None = Field(default=None, gt=0, le=1_000_000, multiple_of=0.01)
    comment: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_request_payload(self) -> "RequestCreate":
        if self.request_type == "leave":
            if self.start_date is None or self.end_date is None:
                raise ValueError("Leave requests require start_date and end_date")
            if self.end_date < self.start_date:
                raise ValueError("end_date must not be before start_date")
            if self.amount is not None:
                raise ValueError("Leave requests cannot include amount")
        elif self.amount is None:
            raise ValueError("Advance requests require a positive amount")
        elif self.start_date is not None or self.end_date is not None:
            raise ValueError("Advance requests cannot include leave dates")
        return self


class RequestReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["approved", "rejected"]
    reviewer_comment: str | None = Field(default=None, max_length=2000)


class RequestResponse(BaseModel):
    id: UUID
    employee_id: UUID
    request_type: RequestType
    status: RequestStatus
    start_date: date | None
    end_date: date | None
    amount: float | None
    comment: str
    reviewer_comment: str | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RequestEventResponse(BaseModel):
    id: UUID
    request_id: UUID
    actor_id: UUID | None
    event_type: Literal["created", "approved", "rejected"]
    from_status: RequestStatus | None
    to_status: RequestStatus
    comment: str
    created_at: datetime


class NotificationResponse(BaseModel):
    id: UUID
    employee_id: UUID
    request_id: UUID | None
    notification_type: str
    title: str
    body: str
    read_at: datetime | None
    created_at: datetime


class CourseProgressUpdate(BaseModel):
    progress_percent: int = Field(ge=0, le=99)


class CourseAssignmentCreate(BaseModel):
    employee_id: str
    course_id: str


class QuizSubmission(BaseModel):
    answers: dict[str, int]


class JanaQuestion(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(min_length=3, max_length=2000)
