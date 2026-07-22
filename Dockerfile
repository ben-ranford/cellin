FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CELLIN_BACKEND=sqlite \
    CELLIN_DATA_DIR=/data

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir ".[mcp,postgresql,neo4j]" \
    && useradd --create-home --uid 10001 cellin \
    && mkdir -p /data \
    && chown -R cellin:cellin /data

USER cellin

ENTRYPOINT ["cellin", "mcp", "serve"]

