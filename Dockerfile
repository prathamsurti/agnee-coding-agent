# ==============================================================================
# AGNI DEV - ROOT ALL-IN-ONE MULTI-STAGE DOCKERFILE
# Packages Redis, FastAPI API-Gateway, Next.js Web-Dashboard & Agent Daemon in ONE FILE
# ==============================================================================

# Stage 1: Base Runtime Environment with Python, Node.js & Redis
FROM python:3.12-slim-bookworm AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NODE_ENV=production \
    PYTHONPATH="/app/apps/api-gateway:/app/apps/agent-daemon:/app/packages/shared-protocol"

# Install Redis Server, Node.js 20, Curl & build essentials
RUN apt-get update && apt-get install -y --no-install-recommends \
    redis-server \
    curl \
    git \
    build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ------------------------------------------------------------------------------
# Stage 2: Backend Target (for microservice compose deployment)
# ------------------------------------------------------------------------------
FROM base AS backend-runner
COPY packages/ packages/
COPY apps/api-gateway/ apps/api-gateway/
COPY seed.py .
EXPOSE 8000
CMD ["uvicorn", "api_gateway.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "apps/api-gateway"]

# ------------------------------------------------------------------------------
# Stage 3: Agent Daemon Target (for microservice compose deployment)
# ------------------------------------------------------------------------------
FROM base AS daemon-runner
COPY packages/ packages/
COPY apps/agent-daemon/ apps/agent-daemon/
EXPOSE 9000
CMD ["python", "apps/agent-daemon/agent_daemon/main.py"]

# ------------------------------------------------------------------------------
# Stage 4: Frontend Builder (Builds Next.js assets)
# ------------------------------------------------------------------------------
FROM node:20-slim AS frontend-builder
WORKDIR /app/apps/web-dashboard
COPY apps/web-dashboard/package*.json ./
RUN npm ci || npm install
COPY apps/web-dashboard/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build || true

# ------------------------------------------------------------------------------
# Stage 5: Frontend Runner Target (for microservice compose deployment)
# ------------------------------------------------------------------------------
FROM node:20-slim AS frontend-runner
WORKDIR /app/apps/web-dashboard
COPY --from=frontend-builder /app/apps/web-dashboard ./
EXPOSE 3000
CMD ["npx", "next", "start", "-p", "3000"]

# ------------------------------------------------------------------------------
# Stage 6: All-In-One Unified Container (DEFAULT TARGET)
# Runs Redis, FastAPI, Next.js Dashboard & Daemon concurrently in a SINGLE container!
# ------------------------------------------------------------------------------
FROM base AS all-in-one

WORKDIR /app

# Copy all application code
COPY packages/ packages/
COPY apps/ apps/
COPY seed.py .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Build Next.js Dashboard inside all-in-one
WORKDIR /app/apps/web-dashboard
RUN npm install && (npm run build || true)
WORKDIR /app

# Expose all operational ports:
# 3000: Web Dashboard
# 8000: API Gateway
# 9000: Agent Daemon WebSocket
# 6379: Redis Hot-Path
EXPOSE 3000 8000 9000 6379

ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]
