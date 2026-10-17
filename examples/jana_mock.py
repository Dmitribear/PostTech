"""Explicit local UI mock, never imported by app.main or shipped in its Docker image.

Run: python -m uvicorn examples.jana_mock:app --host 127.0.0.1 --port 8001
Matches ONLY the listed demo questions; this is not the retrieval implementation.
"""

import json
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.application.dto.digital_hr import JanaQuestion
from app.application.dto.jana import JanaAnswer, JanaArticle

_data = json.loads(
    (Path(__file__).resolve().parents[1] / "knowledge_base/demo/articles.json").read_text(encoding="utf-8")
)
_articles = {article["id"]: article for article in _data["articles"] if article["active"]}


def _normalize(question: str) -> str:
    return " ".join(question.casefold().split()).rstrip("?!. ")


_questions = {
    _normalize(question): article
    for article in _articles.values()
    for question in article["demo_questions"]
}

app = FastAPI(
    title="AI Jana - LOCAL DEMO MOCK",
    description="Synthetic public demo content, no authentication or external services. Not the live AI agent.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/demo/questions")
def demo_questions() -> dict:
    return {"notice": _data["notice"], "questions": [q for a in _articles.values() for q in a["demo_questions"]]}


@app.post("/api/v1/ai/ask", response_model=JanaAnswer)
def ask(payload: JanaQuestion) -> dict:
    article = _questions.get(_normalize(payload.question))
    if article is None:
        return {
            "answer": "В демонстрационной базе нет подтверждённого ответа на этот вопрос. Обратитесь в HR.",
            "sources": [], "grounded": False, "escalation_suggested": True, "mode": "refusal",
        }
    return {
        "answer": article["content"],
        "sources": [{
            "id": article["id"], "title": article["source_title"],
            "url": f"/api/v1/ai/sources/{article['id']}", "excerpt": article["content"][:900],
        }],
        "grounded": True, "escalation_suggested": False, "mode": "excerpts",
    }


@app.get("/api/v1/ai/sources/{article_id}", response_model=JanaArticle)
def source(article_id: UUID) -> dict:
    article = _articles.get(str(article_id))
    if article is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return article
