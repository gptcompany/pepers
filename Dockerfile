# Multi-stage build for research-pipeline services.
# Each service shares the same image, selected via SERVICE build arg.
#
# Build: docker compose build
# Or single: docker build --build-arg SERVICE=orchestrator -t rp-orchestrator .

# Stage 1: Builder — install dependencies
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install .

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /install /usr/local

COPY shared/ shared/
COPY services/ services/

RUN mkdir -p /data/pdfs

ARG SERVICE=orchestrator
ENV SERVICE_NAME=${SERVICE}

CMD ["sh", "-c", "python -m services.${SERVICE_NAME}.main"]
