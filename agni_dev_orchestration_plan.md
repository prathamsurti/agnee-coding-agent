# Agni-Dev (`agni-dev`) Master Orchestration Plan & Executor Specs for Gemini 3.8 Flash

## 1. Brand & Naming Guardrails (`agni-dev` Standard)

Every file, endpoint, environment variable, cookie, and CLI command across the monorepo must strictly use the `agni-dev` / `agni` namespace. Never introduce `aegis` identifiers.

| Component | Canonical `agni-dev` Identifier |
| :--- | :--- |
| **Monorepo & Service Prefix** | `agni-dev`, `agni-api-gateway`, `agni-agent-daemon`, `agni-web-dashboard`, `agni-redis`, `agni-postgres` |
| **CLI Binary & Commands** | `agni login`, `agni logout`, `agni status`, `agni code` |
| **Local Config & AST Cache** | `~/.agni/config.json`, `~/.agni/credentials`, `.agni/ast_cache.bin`, Keychain service `"agni-cli"` |
| **Auth Cookies & Token Prefixes** | `agni_access_token`, `agni_refresh_token`, `agni_rt_<32B>`, `agni_sk_live_<random>` |
| **JWT Issuer & JWKS Key ID** | `iss: "agni-api-gateway"`, `kid: "agni-ed25519-key-1"` |
| **Environment Variables** | `AGNI_API_URL`, `AGNI_API_KEY`, `AGNI_DAEMON_WS_URL` |

> **Existing Naming Bug to Fix in Batch 1**: `apps/web-dashboard/app/page.tsx` line 46 currently renders `Connect Terminal (aegis login)`. Change this to `Connect Terminal (agni login)`.

## 2. Current Codebase Audit & Critical Bug Registry

### 2.1 Critical Runtime Bugs in Existing Files

| ID | File Path | Issue Description | Fix Specification for Gemini 3.8 Flash |
| :--- | :--- | :--- | :--- |
| **BUG-01** | `apps/api-gateway/api_gateway/routers/{auth,device,telemetry}.py` | Imports `from packages.shared_protocol.shared_protocol.schemas import ...`, which raises `ModuleNotFoundError` because the directory on disk is hyphenated (`packages/shared-protocol`). | Add `packages/shared-protocol` to `sys.path` in `api_gateway/__init__.py` (or install as editable package in `Dockerfile`) and import `from shared_protocol.schemas import ...` across all routers. |
| **BUG-02** | `apps/agent-daemon/agent_daemon/main.py`, `Dockerfile`, `entrypoint.sh` | `main.py` uses relative imports (`from .orchestrator import AgentOrchestrator`), which crashes with `ImportError` when invoked as `python apps/agent-daemon/agent_daemon/main.py`. | Add a dual-import fallback or invoke via `PYTHONPATH=apps/agent-daemon:packages/shared-protocol python -m agent_daemon.main` in `Dockerfile` and `entrypoint.sh`. |
| **BUG-03** | `apps/web-dashboard/app/(auth)/login/page.tsx`, `app/activate/page.tsx`, `Dockerfile` | Both pages call `useSearchParams()` in the top-level client component without a `<Suspense>` boundary, causing `next build` to fail during static page generation (`Dockerfile` currently hides this with `npm run build \|\| true`). | Wrap the inner form components that call `useSearchParams()` inside `<Suspense fallback={...}>` and remove `\|\| true` from `Dockerfile` so `next build` succeeds cleanly. |
| **BUG-04** | `apps/api-gateway/api_gateway/routers/auth.py` & `models.py` | `models.py` uses `DateTime(timezone=True)` with naive `datetime.utcnow` defaults, and `auth.py` line 188 compares `session_row.expires_at < datetime.datetime.utcnow()`, raising `TypeError: can't compare offset-naive and offset-aware datetimes` on PostgreSQL (`asyncpg`). | Standardize all timestamps to `datetime.now(datetime.timezone.utc)` (or normalize `expires_at.replace(tzinfo=datetime.timezone.utc)` before comparison). |
| **BUG-05** | `apps/api-gateway/api_gateway/routers/telemetry.py` | `POST /api/v1/telemetry/runs` (`record_agent_run`) only updates an existing row (`if existing:`) and has no `else:` branch, silently dropping all new runs reported by the daemon. | Add the `else:` branch in `record_agent_run` to instantiate and `db.add(AgentRun(...))`, plus increment `Workspace.tokens_consumed`. |
| **BUG-06** | `apps/api-gateway/api_gateway/main.py` & `routers/auth.py` | `jwks` is mounted under `/api/v1/auth/.well-known/jwks.json`, whereas the architecture spec also requires `GET /.well-known/jwks.json` at the root for standard JWKS discovery. | Expose `GET /.well-known/jwks.json` at the root of `app` in `main.py` in addition to `/api/v1/auth/.well-known/jwks.json`. |

### 2.2 Phase-by-Phase Readiness Matrix

| Phase | Current Completion | Implemented Components | Missing / Stubbed Components |
| :--- | :--- | :--- | :--- |
| **Phase 1: Monorepo, DB & Auth** | **75%** | 6 SQLAlchemy models, Ed25519 JWT, Argon2id signup/login/OTP/refresh/logout, RFC 8628 Device Flow, CLI `login`/`logout`/`status`, Next.js `/login`, `/signup`, `/activate`, `/dashboard`. | GitHub OAuth (`/github/login`, `/github/callback`), BYOK & Headless API Key CRUD endpoints (`/api/v1/keys/*`), `/settings/api-keys` UI page, device metadata lookup on `/activate`, local JWKS verification + auto-refresh interceptor in CLI/Daemon, Alembic setup. |
| **Phase 2: AST Engine & Hybrid RAG** | **20%** | Basic Python `ast` skeleton parser in `ast_engine.py`. | Multi-language `tree-sitter` skeleton extraction, `.agni/ast_cache.bin` binary cache, `watchfiles.awatch` incremental file watcher (<5ms updates), and `search_codebase` (`ripgrep` + `rank_bm25` + `pgvector` + Cohere `rerank-v3.5`). |
| **Phase 3: Surgical Diff & Sandbox** | **45%** | 3-stage fuzzy `SEARCH/REPLACE` matcher (`Exact -> Line-Trimmed -> Indentation-Normalized`) and traceback compressor. | File-system patch writer (`apply_surgical_diff`) with Git shadow checkpoints (`git stash create` / rollback on failure) and real 2-container pre-warmed Docker pool (`docker exec`) in `sandbox.py`. |
| **Phase 4: LangGraph & Dual Router** | **15%** | `AgentState` Pydantic model and 5 node method signatures. | Live async LLM calls in `DualModelRouter` (Tier-1 Planner vs. Tier-2 Gemini 3.8 Flash / 2.0 Flash Executor), compiled LangGraph `StateGraph`, parallel read tool execution (`asyncio.gather`), human-in-the-loop interrupt, and 30k-token `ContextCompactor`. |
| **Phase 5: Realtime WS, VS Code & Eval** | **25%** | Basic aiohttp `/ws` endpoint and static diff viewer on `/dashboard`. | Per-node real-time `WsRpcMessage` streaming to `agni code` CLI TUI and Web Dashboard, full `packages/vscode-ext/src/extension.ts` implementation, TypeScript schemas in `packages/shared-protocol`, and headless SWE-bench Lite runner. |

## 3. Sequenced Execution Batches for Gemini 3.8 Flash

Copy and dispatch each batch below to **Gemini 3.8 Flash** in order. After Gemini 3.8 Flash completes a batch, bring the modified files or test output back here for orchestrator verification before moving to the next batch.

### Batch 1: Critical Bug Fixes & Phase 1 Completion (Auth, Keys Vault & Next.js Settings)

#### Scope & Files to Modify/Create
1. `packages/shared-protocol/shared_protocol/schemas.py`
2. `apps/api-gateway/api_gateway/__init__.py` & `main.py`
3. `apps/api-gateway/api_gateway/routers/auth.py`, `device.py`, `telemetry.py`
4. `apps/api-gateway/api_gateway/routers/keys.py` *(New)*
5. `apps/web-dashboard/app/page.tsx`, `app/(auth)/login/page.tsx`, `app/activate/page.tsx`
6. `apps/web-dashboard/app/settings/api-keys/page.tsx` *(New)*
7. `apps/cli/cli/auth.py`
8. `Dockerfile` & `entrypoint.sh`

#### Prompt for Gemini 3.8 Flash (Batch 1)
```text
You are the implementation engineer for the `agni-dev` monorepo. Execute Batch 1 with zero placeholders:

1. Fix Python Module Imports & Entrypoints:
   - In `apps/api-gateway/api_gateway/__init__.py`, ensure `packages/shared-protocol` is added to `sys.path` if not already present, and update `apps/api-gateway/api_gateway/routers/{auth,device,telemetry}.py` to import from `shared_protocol.schemas` instead of `packages.shared_protocol.shared_protocol.schemas`.
   - In `apps/agent-daemon/agent_daemon/main.py`, support running both as `python -m agent_daemon.main` and `python apps/agent-daemon/agent_daemon/main.py` by adding a `sys.path` bootstrap when `__package__` is None. Update `Dockerfile` and `entrypoint.sh` to set `PYTHONPATH=/app/apps/api-gateway:/app/apps/agent-daemon:/app/packages/shared-protocol`.

2. Fix UTC Datetime Comparisons & Telemetry Creation:
   - In `apps/api-gateway/api_gateway/routers/auth.py` and `device.py`, use timezone-aware UTC datetimes (`datetime.datetime.now(datetime.timezone.utc)`) and normalize `session_row.expires_at` before comparison so PostgreSQL `DateTime(timezone=True)` never raises naive/aware `TypeError`.
   - In `apps/api-gateway/api_gateway/routers/telemetry.py`, update `POST /api/v1/telemetry/runs` so that if `existing` is None, it inserts a new `AgentRun` record and increments `Workspace.tokens_consumed` by `req.input_tokens + req.output_tokens`.
   - In `apps/api-gateway/api_gateway/main.py`, expose `GET /.well-known/jwks.json` at the root in addition to `/api/v1/auth/.well-known/jwks.json`.

3. Complete Phase 1 Endpoints (`github` OAuth, Device Metadata Lookup, and `keys` Router):
   - In `apps/api-gateway/api_gateway/routers/auth.py`, add `GET /api/v1/auth/github/login` (redirects to GitHub OAuth authorize URL with client_id/state) and `GET /api/v1/auth/github/callback` (exchanges `code` via `httpx.AsyncClient`, fetches primary verified email, upserts `User` with `email_verified=True` and default `Workspace`, sets `agni_access_token` and `agni_refresh_token` cookies, and redirects to `/dashboard`).
   - In `apps/api-gateway/api_gateway/routers/device.py`, add `GET /api/v1/auth/device/lookup?code={user_code}` returning `{ user_code, client_type, hostname, os_platform, ip, status }` from Redis so `/activate` can display the exact machine details before approval.
   - Create `apps/api-gateway/api_gateway/routers/keys.py` mounted at `/api/v1/keys` with:
     * `GET /api/v1/keys/headless` & `POST /api/v1/keys/headless` (mints `agni_sk_live_<24_hex>`, stores SHA-256 `key_hash` in `api_keys`, returns plaintext key once) & `DELETE /api/v1/keys/headless/{key_id}`.
     * `GET /api/v1/keys/llm` & `POST /api/v1/keys/llm` (encrypts provider key for `ANTHROPIC | OPENAI | GOOGLE | COHERE` using `encrypt_secret(api_key, master_key)` AES-256-GCM into `llm_provider_keys.encrypted_api_key` and `nonce`) & `DELETE /api/v1/keys/llm/{key_id}`.

4. Fix Next.js Build & Add `/settings/api-keys` UI:
   - Fix the typo in `apps/web-dashboard/app/page.tsx` line 46 from `(aegis login)` to `(agni login)`.
   - Wrap `useSearchParams()` consumers in `apps/web-dashboard/app/(auth)/login/page.tsx` and `apps/web-dashboard/app/activate/page.tsx` in `<Suspense>` boundaries so `next build` succeeds without `|| true`. Update `app/activate/page.tsx` to fetch `GET /api/v1/auth/device/lookup?code=...` when a code is present and display `Approve CLI Login from "{hostname}" ({os_platform}, IP: {ip})?`.
   - Create `apps/web-dashboard/app/settings/api-keys/page.tsx` allowing users to create/revoke Headless CI/CD keys (`agni_sk_live_...`) and save AES-256-GCM encrypted BYOK keys (`ANTHROPIC`, `GOOGLE`, `OPENAI`, `COHERE`), and link to it from `app/dashboard/page.tsx`.

5. Sub-Millisecond Local JWKS Verification & Auto-Refresh Interceptor in CLI:
   - In `apps/cli/cli/auth.py`, add `fetch_and_cache_jwks()` (caches `/.well-known/jwks.json` in `~/.agni/jwks.json`), `verify_token_locally(token)` using PyJWT `EdDSA` in <1ms, and an `AgniAuthFlow(httpx.Auth)` class that checks if `exp - now < 60` and automatically calls `silent_refresh()` before dispatching requests.
```

#### Orchestrator Verification Gate for Batch 1
- `python3 -c "import api_gateway.main"` imports cleanly with zero `ModuleNotFoundError`.
- `POST /api/v1/auth/signup` -> `verify-email` -> `refresh` succeeds without timezone `TypeError`.
- `GET /api/v1/auth/device/lookup?code=...` returns machine metadata, and `/api/v1/keys/headless` + `/api/v1/keys/llm` persist records in DB.

### Batch 2: Phase 2 — Tree-sitter Multi-Language AST Engine, Binary Cache & Hybrid Code Search

#### Scope & Files to Modify/Create
1. `apps/agent-daemon/agent_daemon/ast_engine.py`
2. `apps/agent-daemon/agent_daemon/search_engine.py` *(New)*
3. `apps/agent-daemon/agent_daemon/watcher.py` *(New)*
4. `requirements.txt`

#### Prompt for Gemini 3.8 Flash (Batch 2)
```text
You are implementing Phase 2 of `agni-dev` inside `apps/agent-daemon/agent_daemon/`.

1. Upgrade `ast_engine.py` (`AstSkeletonEngine`):
   - Support multi-language AST skeleton extraction (`.py`, `.ts`, `.tsx`, `.js`, `.rs`, `.go`) using `tree_sitter_languages` (or `tree_sitter`) with a deterministic fallback to Python `ast` + regex signature extraction if native tree-sitter wheels are unavailable in a slim environment.
   - Extract class signatures, function/method signatures with type annotations, and top-level imports while stripping function bodies (`...`).
   - Implement binary/msgpack/pickle symbol graph caching at `.agni/ast_cache.bin` keyed by file path and `(mtime_ns, size)` so unchanged files are loaded from `.agni/ast_cache.bin` in <1ms on startup, and provide `update_single_file(file_path)` for incremental updates in <5ms.

2. Create `search_engine.py` (`HybridCodeSearch`):
   - Implement `async def search_codebase(query: str, root_dir: str, top_k: int = 5) -> List[Dict[str, Any]]`:
     * Stage 1 (Lexical Exact): Run `rg --json -n` (ripgrep) asynchronously via `asyncio.create_subprocess_exec` (with pure-Python fallback if `rg` binary is missing) for exact identifier/symbol matches.
     * Stage 2 (BM25): Chunk repository files by AST class/function boundaries and score chunks with `rank_bm25` (`BM25Okapi`) or TF-IDF cosine similarity.
     * Stage 3 (Dense Vector + Reciprocal Rank Fusion): Compute embeddings (via `pgvector` / API embedding provider when configured, falling back to hashed n-gram vector similarity offline) and fuse rankings via Reciprocal Rank Fusion (RRF).
     * Stage 4 (Reranker): If `COHERE_API_KEY` is set, call Cohere `rerank-v3.5` on the top 20 candidates to return the top `top_k` AST chunks with `{ file_path, start_line, end_line, symbol_name, content, score }`.

3. Create `watcher.py` (`IncrementalRepoWatcher`):
   - Use `watchfiles.awatch(root_dir)` in a background `asyncio.Task` (ignoring `.git`, `.agni`, `node_modules`, `__pycache__`, `.next`) to call `AstSkeletonEngine.update_single_file()` and update the BM25/vector index automatically whenever a file is modified on disk.
```

#### Orchestrator Verification Gate for Batch 2
- Building the repo map creates `.agni/ast_cache.bin`, and modifying a single file updates only that file's entry in `<5ms`.
- `HybridCodeSearch.search_codebase("DualModelRouter", ".")` returns the exact AST chunk for `apps/agent-daemon/agent_daemon/router.py` in the top results.

### Batch 3: Phase 3 — Surgical Diff Disk Patcher, Git Shadow Checkpoints & Pre-Warmed Docker Sandbox Pool

#### Scope & Files to Modify/Create
1. `apps/agent-daemon/agent_daemon/patcher.py`
2. `apps/agent-daemon/agent_daemon/sandbox.py`

#### Prompt for Gemini 3.8 Flash (Batch 3)
```text
You are implementing Phase 3 of `agni-dev` in `apps/agent-daemon/agent_daemon/patcher.py` and `sandbox.py`.

1. Upgrade `patcher.py` (`SurgicalDiffPatcher`):
   - Keep the 3-stage in-memory fuzzy matcher (`Exact Match -> Line-Trimmed Match -> Indentation-Normalized Match`).
   - Expand `validate_syntax(code_content, filename)` to validate Python via `ast.parse` and TypeScript/JavaScript/Rust/Go via `tree-sitter` (checking `tree.root_node.has_error` when `tree_sitter` is available, plus balanced delimiter/brace verification).
   - Add Git shadow checkpointing & atomic disk patching:
     * `async def create_git_checkpoint(workspace_path: str) -> Optional[str]`: runs `git stash create` (or `git rev-parse HEAD` if clean) to record a lightweight shadow tree SHA before applying edits.
     * `async def rollback_to_checkpoint(workspace_path: str, checkpoint_sha: str) -> bool`: restores working tree files via `git checkout -- .` or `git read-tree --reset -u {checkpoint_sha}` if verification fails.
     * `async def apply_surgical_diff(workspace_path: str, rel_file_path: str, diff_text: str) -> Dict[str, Any]`: parses all `<<<< SEARCH ... ==== ... >>>> REPLACE` blocks in `diff_text`, applies them sequentially in memory, validates AST syntax, writes atomically to disk only if valid, and returns a unified diff (`difflib.unified_diff`) + status dict.

2. Upgrade `sandbox.py` (`DockerSandboxManager`):
   - Implement a real 2-container pre-warmed Docker pool (`pool_size: int = 2`, image `agni-sandbox:latest` with fallback to `python:3.12-slim-bookworm` or local subprocess isolation when the Docker daemon socket is unavailable).
   - Add `async def initialize_pool(workspace_path: str)` which starts or reuses `agni-sandbox-worker-{0..1}` containers running `tail -f /dev/null` with `workspace_path` bind-mounted at `/workspace`.
   - Acquire an idle container from an `asyncio.Queue` in `run_command_in_sandbox(command, cwd="/workspace")` and execute via `docker exec -w {cwd} {container_name} /bin/sh -c "{command}"` with a 30-second timeout (`asyncio.wait_for`).
   - Enhance `compress_traceback(stderr)` to strip site-packages, pytest internal frames, and node_modules frames while preserving the exact file, line number, failing line, and assertion message.
```

#### Orchestrator Verification Gate for Batch 3
- `apply_surgical_diff` rejects malformed Python syntax without touching disk, writes valid edits atomically, returns a unified diff string, and cleanly rolls back via `rollback_to_checkpoint`.
- `DockerSandboxManager` uses `docker exec` when Docker is available, falls back gracefully in containerless environments, and enforces the 30s timeout.

### Batch 4: Phase 4 — LangGraph Orchestrator, Live Dual-Model Router & Context Compactor

#### Scope & Files to Modify/Create
1. `apps/agent-daemon/agent_daemon/router.py`
2. `apps/agent-daemon/agent_daemon/compactor.py` *(New)*
3. `apps/agent-daemon/agent_daemon/orchestrator.py`
4. `requirements.txt`

#### Prompt for Gemini 3.8 Flash (Batch 4)
```text
You are implementing Phase 4 of `agni-dev` in `apps/agent-daemon/agent_daemon/`.

1. Upgrade `router.py` (`DualModelRouter`):
   - Configure Tier-1 Architect/Planner (`claude-3-7-sonnet-20250219` / `gpt-4o` / `gemini-2.5-pro`) and Tier-2 Fast-Apply Mechanical Executor (`gemini-3.8-flash` / `gemini-2.0-flash` / `claude-3-5-haiku`).
   - Implement `async def generate(self, task_type: Literal["PLANNING", "SURGICAL_EDIT", "LINT_FIX", "TEST_GEN", "CRITIC"], system_prompt: str, user_prompt: str, api_keys: Optional[Dict[str, str]] = None) -> Dict[str, Any]`:
     * Calls Anthropic (`https://api.anthropic.com/v1/messages`), Google Gemini (`https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`), or OpenAI (`https://api.openai.com/v1/chat/completions`) asynchronously using `httpx.AsyncClient`.
     * Tracks and returns `{ content, model, tier, input_tokens, output_tokens, latency_ms }`.
     * Includes a deterministic local AST synthesis fallback when no external API key is configured in `.env` so local E2E tests and CI still run out-of-the-box.

2. Create `compactor.py` (`ContextCompactor`):
   - Estimate token count of message/tool history (`len(text) // 4`).
   - When total context exceeds 30,000 tokens, summarize older tool outputs and failed retry traces while preserving the system prompt, `repo_map`, current `edit_plan`, and most recent `sandbox_results`.

3. Upgrade `orchestrator.py` (`AgentOrchestrator` + LangGraph State Machine):
   - Expand `AgentState` to include `messages`, `repo_map`, `localized_files`, `file_contents`, `edit_plan`, `applied_diffs`, `sandbox_results`, `retry_count`, `input_tokens`, `output_tokens`, `requires_human_approval`, `pending_destructive_command`, and `is_completed`.
   - Implement the 5 nodes with parallel tool execution and real streaming callbacks (`event_callback: Optional[Callable[[str, Dict], Awaitable[None]]]`):
     * `locator_node`: Runs `AstSkeletonEngine.build_repo_map` and `HybridCodeSearch.search_codebase` concurrently via `asyncio.gather()`, then reads the localized files in parallel and emits `FILE_READ`.
     * `planner_node`: Calls Tier-1 Planner to produce a structured JSON step-by-step `edit_plan` + `test_command`. If any planned command matches destructive patterns (`rm -rf`, `DROP TABLE`, `git push --force`), sets `requires_human_approval = True` and pauses for human-in-the-loop approval. Emits `PLAN_CREATED`.
     * `surgical_coder_node`: Calls Tier-2 Fast-Apply Executor (`gemini-3.8-flash` / `gemini-2.0-flash`) to output `<<<< SEARCH ... ==== ... >>>> REPLACE` blocks, applies them via `SurgicalDiffPatcher.apply_surgical_diff`, and emits `DIFF_APPLIED`.
     * `verifier_node`: Runs linter + unit tests inside `DockerSandboxManager.run_command_in_sandbox` and emits `TEST_OUTPUT`.
     * `critic_node`: Inspects exit code and compressed traceback. If exit code == 0, marks `is_completed = True`. If non-zero and `retry_count < max_retries` (3), appends compressed stderr, runs `ContextCompactor`, and loops back to `surgical_coder_node`; if retries exhausted, rolls back to the Git shadow checkpoint.
   - Build the graph using `langgraph.graph.StateGraph` (with an automatic state-machine fallback runner if `langgraph` is not installed) and post final run telemetry to `POST /api/v1/telemetry/runs`.
```

#### Orchestrator Verification Gate for Batch 4
- Running `orchestrator.run_pipeline(prompt)` executes `LocatorNode -> PlannerNode -> SurgicalCoderNode -> VerifierNode -> CriticNode`, streams events at each transition, increments token counters, and records telemetry.

### Batch 5: Phase 5 — Live WebSocket Bus, CLI TUI, VS Code Extension & SWE-bench Lite Harness

#### Scope & Files to Modify/Create
1. `apps/agent-daemon/agent_daemon/main.py`
2. `apps/cli/cli/main.py`
3. `apps/web-dashboard/app/dashboard/page.tsx`
4. `packages/shared-protocol/index.ts` *(New)*
5. `packages/vscode-ext/src/extension.ts`
6. `eval/swebench_harness.py` *(New)*

#### Prompt for Gemini 3.8 Flash (Batch 5)
```text
You are implementing Phase 5 of `agni-dev` across the daemon, CLI, Web Dashboard, VS Code Extension, and Evaluation Harness.

1. Real-Time WebSocket Event Bus (`apps/agent-daemon/agent_daemon/main.py`):
   - Maintain a set of connected WebSocket clients so both the initiating client (CLI/VS Code) and observer clients (Next.js Dashboard) receive real-time `WsRpcMessage` broadcasts (`PLAN_CREATED`, `FILE_READ`, `DIFF_APPLIED`, `TEST_OUTPUT`, `HUMAN_APPROVAL_REQUIRED`, `ERROR`, `DONE`) as each node executes.
   - Verify the caller's Ed25519 JWT or `AGNI_API_KEY` on WebSocket handshake (`Authorization` header or `?token=` query param).
   - Support `APPROVE_COMMAND` / `REJECT_COMMAND` WebSocket actions to resume human-in-the-loop interrupts.

2. Connect `agni code` CLI TUI to Live Daemon (`apps/cli/cli/main.py`):
   - Replace the `time.sleep()` mock in `agni code` with a live WebSocket client (using `aiohttp` or `httpx`/`websockets`) connecting to `ws://localhost:9000/ws`.
   - Stream each real-time event (`PLAN_CREATED`, `FILE_READ`, `DIFF_APPLIED`, `TEST_OUTPUT`, `DONE`) into a live Rich TUI panel, prompt the user interactively if `HUMAN_APPROVAL_REQUIRED` arrives, and render the syntax-highlighted unified diff upon completion.

3. Live WebSocket Subscription in Next.js (`apps/web-dashboard/app/dashboard/page.tsx`):
   - Connect the dashboard to `ws://localhost:9000/ws` to display live active node status (`Locator -> Planner -> SurgicalCoder -> Verifier -> Critic`), real-time token counters, and side-by-side / unified diff updates without requiring a page refresh.

4. Complete TypeScript Shared Protocol & VS Code Extension:
   - Create `packages/shared-protocol/index.ts` exporting TypeScript interfaces matching `schemas.py` (`TokenResponse`, `DeviceInitResponse`, `WsRpcMessage`, `AgentRunTelemetry`).
   - Implement `packages/vscode-ext/src/extension.ts` with:
     * `agni.login`: Triggers RFC 8628 `/api/v1/auth/device/init`, shows a VS Code notification with "Open Browser to Authorize (`ABCD-EFGH`)", polls `/api/v1/auth/device/poll`, and stores tokens in `context.secrets`.
     * `agni.code`: Prompts via `vscode.window.showInputBox`, connects to `ws://localhost:9000/ws`, streams progress to a dedicated `"Agni Dev"` OutputChannel, and opens VS Code's native diff viewer (`vscode.commands.executeCommand('vscode.diff', ...)`) when `DIFF_APPLIED` arrives.

5. Create Headless SWE-bench Lite Evaluation Harness (`eval/swebench_harness.py`):
   - Build an async evaluation script supporting `AGNI_API_KEY` headless authentication that runs a configurable slice of SWE-bench Lite tasks (default 50 tasks or a local benchmark JSONL fixture), executes `AgentOrchestrator.run_pipeline` per instance, and outputs a JSON + Markdown scorecard reporting `Pass@1`, `Pass@3`, `Localization Recall@5`, average tokens per run, and average step latency in ms.
```

#### Orchestrator Verification Gate for Batch 5
- `agni code "..."` connects over WebSocket to `ws://localhost:9000/ws` and renders real-time node events and diffs.
- `packages/vscode-ext/src/extension.ts` implements both `agni.login` and `agni.code` with zero stub comments.
- `python eval/swebench_harness.py --dry-run` produces the full Pass@1 / Pass@3 / Recall@5 telemetry scorecard.
