FROM python:3.12-slim AS api

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt 'psycopg[binary]>=3.2,<4' \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app

COPY app ./app
COPY knowledge_base ./knowledge_base
COPY scripts ./scripts

USER app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM api AS bootstrap
COPY database ./database
COPY docker/local ./docker/local
CMD ["python", "docker/local/bootstrap.py"]
