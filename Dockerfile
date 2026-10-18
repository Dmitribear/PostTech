FROM python:3.13-slim AS api

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
COPY scripts/telegram_worker.py ./scripts/telegram_worker.py

USER app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM api AS bootstrap
USER root
RUN pip install --no-cache-dir "psycopg[binary]>=3.2,<4"
COPY database ./database
COPY docker/local ./docker/local
USER app
CMD ["python", "docker/local/bootstrap.py"]

FROM api AS production
