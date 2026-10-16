"""Explicit localhost demo: real local model, fictional data, no authentication.

python -m uvicorn examples.jana_local_demo:app --host 127.0.0.1 --port 8002
Never mount this app in the production API or expose it to the Internet.
"""

import json
from datetime import date
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict

from app.core.config import get_settings
from app.schemas.digital_hr import JanaQuestion
from app.schemas.jana import JanaAnswer, JanaArticle
from app.services.calendar_export import CalendarExportUnavailable, leave_calendar
from app.services.jana_errors import JanaUnavailable
from app.services.jana_local import answer_from_faq, get_index

ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="Jana: local model / fictional demo only")
DEMO_LEAVE = {"id": "30000000-0000-4000-8000-000000000001", "request_type": "leave",
              "status": "approved", "start_date": "2026-11-10", "end_date": "2026-11-15"}


def articles() -> list[dict]:
    return json.loads((ROOT / "knowledge_base/demo/articles.json").read_text(encoding="utf-8"))["articles"]


@app.post("/api/v1/ai/ask", response_model=JanaAnswer)
def ask(payload: JanaQuestion):
    settings = get_settings()
    try:
        return answer_from_faq(payload.question, articles(), get_index(settings),
                               settings.jana_min_score, settings.jana_score_margin)
    except JanaUnavailable as exc:
        raise HTTPException(503, "Local model unavailable. Run python -m scripts.prepare_jana_local") from exc


@app.get("/api/v1/ai/sources/{article_id}", response_model=JanaArticle)
def source(article_id: UUID):
    for article in articles():
        if article["id"] == str(article_id) and article.get("active"):
            return article
    raise HTTPException(404, "Source not found")


@app.get("/demo/leave.ics")
def calendar():
    return Response(leave_calendar(DEMO_LEAVE, demo=True), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="demo-leave.ics"', "Cache-Control": "no-store"})


class DemoLeave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    start_date: date
    end_date: date


@app.post("/demo/leave.ics")
def portal_calendar(payload: DemoLeave):
    """Fictional portal dates only. Production always reads authorized DB records."""
    try:
        content = leave_calendar({**payload.model_dump(mode="json"), "request_type": "leave", "status": "approved"}, demo=True)
    except CalendarExportUnavailable as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(content, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="demo-leave.ics"', "Cache-Control": "no-store"})


@app.get("/", response_class=HTMLResponse)
def page():
    return (ROOT / "examples/jana_local_demo.html").read_text(encoding="utf-8")
