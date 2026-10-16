from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class RequestCreate(BaseModel):
    request_type: Literal["leave", "advance"]
    start_date: date | None = None
    end_date: date | None = None
    amount: float | None = Field(default=None, gt=0, le=1_000_000)
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
    status: Literal["approved", "rejected"]
    reviewer_comment: str | None = Field(default=None, max_length=2000)


class CourseProgressUpdate(BaseModel):
    progress_percent: int = Field(ge=0, le=99)


class CourseAssignmentCreate(BaseModel):
    employee_id: str
    course_id: str


class QuizSubmission(BaseModel):
    answers: dict[str, int]


class JanaQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
