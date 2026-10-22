import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from packages.shared_protocol.shared_protocol.schemas import AgentRunCreate, AgentRunTelemetry
from ..database import get_db
from ..models import AgentRun, Workspace
from ..security import verify_access_token

router = APIRouter(prefix="/api/v1/telemetry", tags=["Telemetry & Observability"])

async def get_current_user_claims(request: Request) -> dict:
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
    elif "agni_access_token" in request.cookies:
        token = request.cookies.get("agni_access_token")

    if not token:
        # Allow dev fallback if testing locally without headers
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
    # Look up or create run
    run_uuid = uuid.UUID(req.run_id) if req.run_id else uuid.uuid4()
    stmt = select(AgentRun).where(AgentRun.id == run_uuid)
    existing = (await db.execute(stmt)).scalars().first()

    if existing:
        existing.status = req.status
        existing.iterations = req.iterations
        existing.input_tokens = req.input_tokens
        existing.output_tokens = req.output_tokens
        existing.duration_ms = req.duration_ms
        if req.final_diff:
            existing.final_diff = req.final_diff
    await db.commit()
    return {"message": "Telemetry updated", "run_id": str(run_uuid)}
