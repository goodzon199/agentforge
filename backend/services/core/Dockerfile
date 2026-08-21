FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY services/core/requirements.txt /app/requirements.txt
COPY shared/ /app/shared_src/
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && pip install --no-cache-dir /app/shared_src/

COPY services/core/ /app/

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host ${API_HOST:-0.0.0.0} --port ${API_PORT:-8000}"]