# 🔥 agni-dev: Ultra-Fast Autonomous Coding Agent Monorepo

[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg?logo=docker)](https://www.docker.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-14_App_Router-black.svg?logo=next.js)](https://nextjs.org/)
[![Redis](https://img.shields.io/badge/Redis-7_Alpine-red.svg?logo=redis)](https://redis.io/)
[![PostgreSQL](https://img.shields.io/badge/Postgres_16-pgvector-336791.svg?logo=postgresql)](https://github.com/pgvector/pgvector)
[![Ed25519](https://img.shields.io/badge/Auth-Ed25519_Asymmetric_JWT-brightgreen.svg)]()

`agni-dev` decouples the Core Agent Daemon from client surfaces (CLI, Web Dashboard, VS Code) so the exact same engine can run interactively on your laptop or headlessly in CI/CD pipelines.

---

## 🏛️ Monorepo Architecture

```plaintext
agni-dev/
├── Dockerfile                # Root ALL-IN-ONE Dockerfile (Runs everything in 1 file)
├── docker-compose.yml        # Orchestrates Redis 7, Postgres 16 (pgvector), API, UI & Daemon
├── seed.py                   # Automated Database Seeding Script (Admin, Keys, Diffs)
├── generate_keys.py          # Ed25519 Cryptographic Keypair Generator
├── apps/
│   ├── api-gateway/          # FastAPI, Ed25519 JWT Auth, RFC 8628 Device Flow, Telemetry
│   ├── web-dashboard/        # Next.js 14 App Router, Dark Mode UI, Monaco Diff Viewer
│   ├── agent-daemon/         # LangGraph Engine: Dual-Model Router + Tree-sitter + Sandbox
│   └── cli/                  # Python Typer + Rich TUI ("agni login", "agni code", "agni status")
├── packages/
│   ├── vscode-ext/           # VS Code Extension (WebSocket JSON-RPC Bridge)
│   └── shared-protocol/      # Pydantic & TypeScript schemas for Auth, Telemetry & Events
└── infra/
    ├── docker-compose.yml    # Infrastructure definitions
    └── sandbox.Dockerfile    # Pre-warmed sandbox pool container (Python, Node, Rust, Pyright)
```

---

## ⚡ Option 1: Run Everything in One File (Root Dockerfile)

A unified multi-stage root [`Dockerfile`](file:///h:/Codebase/agnee-coding-agent/Dockerfile) is provided that boots Redis, runs database migrations, seeds the database, and launches the API Gateway, Next.js Dashboard, and Agent Daemon in a **single container**:

```bash
# 1. Build the All-in-One Container
docker build -t agni-all-in-one .

# 2. Run the Container (Maps Dashboard, API Gateway, Agent Daemon & Redis)
docker run -d \
  --name agni-stack \
  -p 3000:3000 \
  -p 8000:8000 \
  -p 9000:9000 \
  -p 6379:6379 \
  agni-all-in-one
```

Once running, access:
- **Web Dashboard & Diff Viewer**: [http://localhost:3000](http://localhost:3000)
- **API Gateway & Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Device Activation URL**: [http://localhost:3000/activate](http://localhost:3000/activate)
- **Agent Daemon WebSocket**: `ws://localhost:9000/ws`

---

## 🐳 Option 2: Run via Docker Compose (Recommended for Production)

Uses Docker for Redis 7 and PostgreSQL 16 (with `pgvector`):

```bash
# Start all microservices together
docker compose up --build -d

# View service logs
docker compose logs -f
```

To stop the services:
```bash
docker compose down
```

---

## 💻 Option 3: Local Development (Bare Metal)

### 1. Start Redis & Postgres using Docker
```bash
# Start only Redis & Postgres containers in background
docker run -d --name agni-redis -p 6379:6379 redis:7-alpine
docker run -d --name agni-postgres -p 5432:5432 -e POSTGRES_USER=agni -e POSTGRES_PASSWORD=agni_secret -e POSTGRES_DB=agni_db pgvector/pgvector:pg16
```

### 2. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 3. Seed Database
```bash
python seed.py
```

### 4. Run Services Concurrently
- **Terminal 1 (API Gateway)**:
  ```bash
  uvicorn api_gateway.main:app --reload --port 8000 --app-dir apps/api-gateway
  ```
- **Terminal 2 (Agent Daemon)**:
  ```bash
  python apps/agent-daemon/agent_daemon/main.py
  ```
- **Terminal 3 (Next.js Dashboard)**:
  ```bash
  cd apps/web-dashboard
  npm install
  npm run dev
  ```

---

## 🔑 Seeding Information & Credentials

The repository includes an automated seed script ([`seed.py`](file:///h:/Codebase/agnee-coding-agent/seed.py)). You can execute it at any time with:

```bash
python seed.py
```

### Default Seeded Records

| Entity | Field | Seeded Value |
| :--- | :--- | :--- |
| **Admin User** | Email | `admin@agni.dev` |
| | Password | `Password123!` (Argon2id hashed) |
| | Verification | `email_verified = True` |
| **Workspace** | Name | `Agni Core Workspace` |
| | Plan Tier | `PRO` |
| | Monthly Token Limit | `5,000,000` |
| | Consumed Tokens | `124,500` |
| **Headless Key** | Live Key | `agni_sk_live_masterkey999988887777` |
| | Scopes | `["read", "write", "sandbox", "telemetry"]` |
| **Telemetry Runs** | 2 Sample Runs | Populated with real AST diffs, duration & token metrics |

---

## 📱 RFC 8628 OAuth 2.0 Device Flow (`agni login`)

### Terminal Login Flow:
1. In your terminal, run:
   ```bash
   python -m apps.cli.cli.main login
   ```
2. The CLI gathers machine metadata and contacts `POST /api/v1/auth/device/init`.
3. It displays a formatted Rich Panel with:
   - **Verification URL**: `http://localhost:3000/activate?code=ABCD-EFGH`
   - **8-character code**: e.g., `ABCD-EFGH`
4. Open the link in your browser and click **Authorize Machine**.
5. The CLI background poller receives approval, mints the session, writes `~/.agni/config.json`, and stores the refresh token securely in your OS Keychain!

### Check Status & Run Coding Task:
```bash
# Verify session and token details
python -m apps.cli.cli.main status

# Run an agent coding task
python -m apps.cli.cli.main code "Implement dual-model routing logic in router.py"
```

---

## 🚀 Speed Architecture (How Agni Maximizes Performance)

1. **Dual-Model Router (`apps/agent-daemon/agent_daemon/router.py`)**:
   - **Tier-1 Architect** (Claude 3.7 Sonnet / Opus): Only called for initial problem scoping and multi-file architecture planning.
   - **Tier-2 Fast-Apply Executor** (Gemini 2.0 Flash / Haiku): Executes surgical code edits and lint fixes at 200–300+ tokens/sec.
2. **Sub-millisecond Local Ed25519 Auth**:
   - The CLI and Daemon fetch the Gateway's public Ed25519 key from `GET /.well-known/jwks.json` and verify every local RPC call in **~0.2ms** without hitting PostgreSQL.
3. **Deterministic 3-Stage Fuzzy Patcher (`apps/agent-daemon/agent_daemon/patcher.py`)**:
   - Matches `<<<< SEARCH ... ==== ... >>>> REPLACE` blocks using Exact Match $\rightarrow$ Line-Trimmed Match $\rightarrow$ Indentation-Normalized Match.
   - Validates in-memory AST syntax before touching disk.
4. **Pre-Warmed Docker Sandbox (`apps/agent-daemon/agent_daemon/sandbox.py`)**:
   - Pre-warmed container pool starts test executions in ~30ms.
   - Automatically prunes framework stack traces to prevent LLM context pollution.
