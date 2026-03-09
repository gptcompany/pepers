# Multi-stage build for PePeRS services.
# Each service shares the same image, selected via SERVICE build arg.
#
# Build: docker compose build
# Or single: docker build --build-arg SERVICE=orchestrator -t pepers-orchestrator .

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

# Node.js for CLI LLM providers (claude, codex, gemini)
COPY --from=node:20-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:20-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli \
    && npm cache clean --force

COPY --from=builder /install /usr/local

COPY shared/ shared/
COPY services/ services/

RUN groupadd -g 1000 pepers \
    && useradd -m -u 1000 -g 1000 -s /bin/bash pepers \
    && mkdir -p /data/pdfs \
    && chown -R 1000:1000 /data /app /home/pepers

ARG SERVICE=orchestrator
ENV SERVICE_NAME=${SERVICE}

CMD ["sh", "-c", "python -m services.${SERVICE_NAME}.main"]
