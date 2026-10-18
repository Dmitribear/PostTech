FROM python:3.12-slim
WORKDIR /app
COPY scripts/prepare_jana_reader.py ./scripts/prepare_jana_reader.py
COPY knowledge_base/reader-model.json ./knowledge_base/reader-model.json
COPY docker/reader/download_model.py ./docker/reader/download_model.py
ENTRYPOINT ["python", "docker/reader/download_model.py"]
