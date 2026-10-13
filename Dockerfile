# CPU-only image. The saved artifacts were trained and evaluated on CPU-sized
# inputs, and the default PyPI torch wheel is the CUDA build, which would add
# gigabytes to the image and a GPU runtime dependency this service never uses.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    KERAS_BACKEND=torch \
    IDX_ARTIFACT_DIR=/app/models \
    IDX_RESEARCH_DATA_DIR=/app/data/research \
    IDX_SQLITE_PATH=/app/data/sinyal.sqlite3

WORKDIR /app

COPY requirements-torch-cpu.txt ./
RUN pip install --no-cache-dir -r requirements-torch-cpu.txt \
    && python -c "import torch; assert torch.version.cuda is None"

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY idx_signal ./idx_signal
COPY models ./models
COPY data/research ./data/research

# Vercel injects PORT; a plain `docker run` falls back to 80.
ENV PORT=80
EXPOSE 80

CMD ["sh", "-c", "uvicorn idx_signal.api:app --host 0.0.0.0 --port ${PORT}"]
