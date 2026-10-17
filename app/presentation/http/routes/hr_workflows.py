from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.application.use_cases import hr_workflows as use_cases
from app.application.use_cases.hr_workflows import (
    EnrollmentInput,
    FulfillInput,
    ImportInput,
    PolicyInput,
    TrackInput,
)
from app.domain.models import UserContext
from app.presentation.http.responses import render_result
from app.presentation.http.security import get_current_user

router = APIRouter(prefix="/workspace", tags=["HR workflows"])


@router.get("/fulfillment")
def fulfillment_queue(
    offset: int = Query(0, ge=0),
    state: Literal["awaiting_hr", "processing", "completed"] = "awaiting_hr",
    actor: UserContext = Depends(get_current_user),
):
    return render_result(
        use_cases.fulfillment_queue(offset=offset, state=state, actor=actor)
    )


@router.get("/fulfillment/{request_id}")
def fulfillment_detail(
    request_id: UUID, actor: UserContext = Depends(get_current_user)
):
    return render_result(
        use_cases.fulfillment_detail(request_id=request_id, actor=actor)
    )


@router.post("/fulfillment/{request_id}")
def fulfill(
    request_id: UUID,
    payload: FulfillInput,
    actor: UserContext = Depends(get_current_user),
):
    return render_result(
        use_cases.fulfill(request_id=request_id, payload=payload, actor=actor)
    )


@router.get("/employee-import/template")
def import_template(actor: UserContext = Depends(get_current_user)):
    return render_result(use_cases.import_template(actor=actor))


@router.post("/employee-import/preview")
def import_preview(
    payload: ImportInput, actor: UserContext = Depends(get_current_user)
):
    return render_result(use_cases.import_preview(payload=payload, actor=actor))


@router.post("/employee-import/{batch_id}/apply")
def import_apply(batch_id: UUID, actor: UserContext = Depends(get_current_user)):
    return render_result(use_cases.import_apply(batch_id=batch_id, actor=actor))


@router.get("/tracks")
def tracks(actor: UserContext = Depends(get_current_user)):
    return render_result(use_cases.tracks(actor=actor))


@router.post("/tracks", status_code=201)
def create_track(payload: TrackInput, actor: UserContext = Depends(get_current_user)):
    return render_result(use_cases.create_track(payload=payload, actor=actor))


@router.delete("/tracks/{track_id}")
def archive_track(track_id: UUID, actor: UserContext = Depends(get_current_user)):
    return render_result(use_cases.archive_track(track_id=track_id, actor=actor))


@router.post("/tracks/{track_id}/enroll")
def enroll(
    track_id: UUID,
    payload: EnrollmentInput,
    actor: UserContext = Depends(get_current_user),
):
    return render_result(
        use_cases.enroll(track_id=track_id, payload=payload, actor=actor)
    )


@router.get("/my-tracks")
def my_tracks(
    employee_id: UUID | None = None, actor: UserContext = Depends(get_current_user)
):
    return render_result(use_cases.my_tracks(employee_id=employee_id, actor=actor))


@router.get("/summary")
def summary(actor: UserContext = Depends(get_current_user)):
    return render_result(use_cases.summary(actor=actor))


@router.get("/workflow-policy")
def policy(actor: UserContext = Depends(get_current_user)):
    return render_result(use_cases.policy(actor=actor))


@router.put("/workflow-policy")
def save_policy(payload: PolicyInput, actor: UserContext = Depends(get_current_user)):
    return render_result(use_cases.save_policy(payload=payload, actor=actor))


@router.post("/workflow-policy/run")
def run_policy(actor: UserContext = Depends(get_current_user)):
    return render_result(use_cases.run_policy(actor=actor))
