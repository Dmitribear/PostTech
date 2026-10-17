FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app

COPY app ./app
COPY knowledge_base ./knowledge_base
COPY scripts/integration_worker.py ./scripts/integration_worker.py
COPY scripts/workflow_worker.py ./scripts/workflow_worker.py
COPY scripts/background_worker.py ./scripts/background_worker.py

USER app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
