import uuid
import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from shared_protocol.schemas import AgentRunCreate, AgentRunTelemetry
from ..database import get_db
from ..models import AgentRun, Workspace, User
from ..security import verify_access_token

router = APIRouter(prefix="/api/v1/telemetry", tags=["Telemetry & Observability"])

def now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)

async def get_current_user_claims(request: Request) -> dict:
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
    elif "agni_access_token" in request.cookies:
        token = request.cookies.get("agni_access_token")

    if not token:
        return {"sub": str(uuid.uuid4()), "ws": str(uuid.uuid4())}

    try:
        return verify_access_token(token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

@router.get("/runs")
async def list_agent_runs(db: AsyncSession = Depends(get_db)):
    stmt = select(AgentRun).order_by(desc(AgentRun.created_at)).limit(50)
    runs = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "repo_name": r.repo_name,
            "task_prompt": r.task_prompt,
            "status": r.status,
            "iterations": r.iterations,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "duration_ms": r.duration_ms,
            "final_diff": r.final_diff,
            "created_at": r.created_at.isoformat() if r.created_at else None
        }
        for r in runs
    ]

@router.post("/runs")
async def record_agent_run(req: AgentRunTelemetry, db: AsyncSession = Depends(get_db)):
    run_uuid = uuid.UUID(req.run_id) if req.run_id else uuid.uuid4()
    stmt = select(AgentRun).where(AgentRun.id == run_uuid)
    existing = (await db.execute(stmt)).scalars().first()

    total_tokens = (req.input_tokens or 0) + (req.output_tokens or 0)

    if existing:
        existing.status = req.status
        existing.iterations = req.iterations
        existing.input_tokens = req.input_tokens
        existing.output_tokens = req.output_tokens
        existing.duration_ms = req.duration_ms
        if req.final_diff:
            existing.final_diff = req.final_diff

        # Increment workspace token usage
        ws = (await db.execute(select(Workspace).where(Workspace.id == existing.workspace_id))).scalars().first()
        if ws:
            ws.tokens_consumed += total_tokens
    else:
        # Resolve target workspace and user
        workspace = None
        if req.workspace_id:
            try:
                ws_id = uuid.UUID(req.workspace_id)
                workspace = (await db.execute(select(Workspace).where(Workspace.id == ws_id))).scalars().first()
            except Exception:
                pass
        
        if not workspace:
            workspace = (await db.execute(select(Workspace).order_by(desc(Workspace.created_at)))).scalars().first()

        if not workspace:
            # Create fallback workspace & user if empty
            u_id = uuid.uuid4()
            w_id = uuid.uuid4()
            fallback_user = User(
                id=u_id,
                email="default@agni.dev",
                name="Default User",
                email_verified=True,
                created_at=now_utc()
            )
            workspace = Workspace(
                id=w_id,
                owner_id=u_id,
                name="Default Workspace",
                slug="default-ws",
                plan_tier="FREE",
                monthly_token_limit=500_000,
                tokens_consumed=0,
                created_at=now_utc()
            )
            db.add(fallback_user)
            db.add(workspace)
            await db.flush()

        user_id = uuid.UUID(req.user_id) if req.user_id else workspace.owner_id

        new_run = AgentRun(
            id=run_uuid,
            workspace_id=workspace.id,
            user_id=user_id,
            repo_name=req.repo_name or "agni-dev/core",
            task_prompt=req.task_prompt or "Autonomous task execution",
            status=req.status,
            iterations=req.iterations,
            input_tokens=req.input_tokens,
            output_tokens=req.output_tokens,
            final_diff=req.final_diff,
            duration_ms=req.duration_ms,
            created_at=now_utc()
        )
        db.add(new_run)
        workspace.tokens_consumed += total_tokens

    await db.commit()
    return {"message": "Telemetry recorded successfully", "run_id": str(run_uuid)}
