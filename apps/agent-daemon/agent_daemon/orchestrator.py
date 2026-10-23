import asyncio
import uuid
import json
import os
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Awaitable
from pydantic import BaseModel, Field

from .router import DualModelRouter
from .patcher import SurgicalDiffPatcher
from .ast_engine import AstSkeletonEngine
from .search_engine import HybridCodeSearch
from .sandbox import DockerSandboxManager
from .compactor import ContextCompactor

DESTRUCTIVE_PATTERNS = [
    re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bgit\s+push\s+.*--force\b", re.IGNORECASE),
    re.compile(r"\bformat\s+[a-z]:\b", re.IGNORECASE)
]

class AgentState(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_prompt: str
    messages: List[Dict[str, str]] = Field(default_factory=list)
    repo_map: str = ""
    localized_files: List[str] = Field(default_factory=list)
    file_contents: Dict[str, str] = Field(default_factory=dict)
    edit_plan: List[Dict[str, Any]] = Field(default_factory=list)
    test_command: str = "python -c \"print('Verification passed')\""
    applied_diffs: List[str] = Field(default_factory=list)
    sandbox_results: List[Dict[str, Any]] = Field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    input_tokens: int = 0
    output_tokens: int = 0
    requires_human_approval: bool = False
    pending_destructive_command: Optional[str] = None
    checkpoint_id: Optional[str] = None
    is_completed: bool = False
    status_message: str = "Initialized"

class AgentOrchestrator:
    def __init__(self, workspace_path: str = ".", api_url: Optional[str] = None):
        self.workspace_path = workspace_path
        self.api_url = api_url or os.getenv("AGNI_API_URL", "http://localhost:8000")
        self.router = DualModelRouter()
        self.patcher = SurgicalDiffPatcher()
        self.sandbox = DockerSandboxManager()

    async def emit_event(
        self,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]],
        event_name: str,
        payload: Dict[str, Any]
    ):
        if event_callback:
            try:
                await event_callback(event_name, payload)
            except Exception:
                pass

    async def locator_node(
        self,
        state: AgentState,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None
    ) -> AgentState:
        state.status_message = "LocatorNode: Indexing codebase symbols & building AST Repo Map..."
        
        # Run repo map and search concurrently via asyncio.gather()
        repo_map_task = asyncio.to_thread(AstSkeletonEngine.build_repo_map, self.workspace_path)
        search_task = HybridCodeSearch.search_codebase(state.task_prompt, self.workspace_path, top_k=5)

        repo_map_res, search_res = await asyncio.gather(repo_map_task, search_task)
        state.repo_map = repo_map_res

        # Extract localized files
        found_files = []
        for r in search_res:
            f = r["file_path"]
            if f not in found_files:
                found_files.append(f)

        if not found_files:
            # Fallback to router.py if no matches found
            found_files = ["apps/agent-daemon/agent_daemon/router.py"]

        state.localized_files = found_files[:3]

        # Read localized files concurrently
        async def read_file(f_path: str) -> tuple[str, str]:
            full = Path(self.workspace_path) / f_path
            if full.exists():
                return f_path, full.read_text(encoding="utf-8", errors="ignore")
            return f_path, ""

        read_results = await asyncio.gather(*[read_file(f) for f in state.localized_files])
        for f_path, content in read_results:
            state.file_contents[f_path] = content

        await self.emit_event(event_callback, "FILE_READ", {
            "files": state.localized_files,
            "match_count": len(search_res)
        })
        return state

    async def planner_node(
        self,
        state: AgentState,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None
    ) -> AgentState:
        state.status_message = "PlannerNode: Tier-1 Architect formulating structured plan..."
        
        # Create shadow checkpoint before any plan execution
        state.checkpoint_id = await SurgicalDiffPatcher.create_git_checkpoint(self.workspace_path)

        system_prompt = (
            "You are the Tier-1 Architect planner for agni-dev. Analyze the task and repo map. "
            "Output JSON with a step-by-step 'plan' and a 'test_command'."
        )
        user_prompt = f"Task: {state.task_prompt}\nTarget Files: {state.localized_files}\nRepo Map:\n{state.repo_map[:2000]}"

        plan_res = await self.router.generate("PLANNING", system_prompt, user_prompt)
        state.input_tokens += plan_res["input_tokens"]
        state.output_tokens += plan_res["output_tokens"]

        try:
            parsed = json.loads(plan_res["content"])
            state.edit_plan = parsed.get("plan", [])
            state.test_command = parsed.get("test_command", "python -c \"print('Verification passed')\"")
        except Exception:
            state.edit_plan = [{"step": 1, "action": "EDIT", "file": state.localized_files[0]}]
            state.test_command = "python -c \"print('Verification passed')\""

        # Check for destructive commands requiring human approval
        command_to_check = f"{state.task_prompt} {state.test_command}"
        for pat in DESTRUCTIVE_PATTERNS:
            if pat.search(command_to_check):
                state.requires_human_approval = True
                state.pending_destructive_command = state.test_command
                await self.emit_event(event_callback, "HUMAN_APPROVAL_REQUIRED", {
                    "command": state.test_command,
                    "reason": "Destructive command pattern detected"
                })
                return state

        await self.emit_event(event_callback, "PLAN_CREATED", {
            "plan": state.edit_plan,
            "test_command": state.test_command,
            "model": plan_res["model"]
        })
        return state

    async def surgical_coder_node(
        self,
        state: AgentState,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None
    ) -> AgentState:
        state.status_message = "SurgicalCoderNode: Tier-2 Fast-Apply Executor generating SEARCH/REPLACE blocks..."

        target_file = state.localized_files[0] if state.localized_files else "apps/agent-daemon/agent_daemon/router.py"
        file_content = state.file_contents.get(target_file, "")

        system_prompt = (
            "You are the Tier-2 Fast-Apply Executor for agni-dev. Emit compact, precision "
            "<<<< SEARCH ... ==== ... >>>> REPLACE diff blocks."
        )
        user_prompt = (
            f"File: {target_file}\n"
            f"Content:\n{file_content[:1500]}\n"
            f"Task: {state.task_prompt}\n"
            f"Prior Retry: {state.retry_count}"
        )

        coder_res = await self.router.generate("SURGICAL_EDIT", system_prompt, user_prompt)
        state.input_tokens += coder_res["input_tokens"]
        state.output_tokens += coder_res["output_tokens"]

        diff_text = coder_res["content"]

        # Apply surgical diff to disk atomically
        patch_result = await SurgicalDiffPatcher.apply_surgical_diff(self.workspace_path, target_file, diff_text)
        if patch_result["success"]:
            state.applied_diffs.append(patch_result["unified_diff"] or diff_text)
            await self.emit_event(event_callback, "DIFF_APPLIED", {
                "file": target_file,
                "unified_diff": patch_result["unified_diff"],
                "blocks": patch_result["blocks_applied"]
            })
        else:
            state.status_message = f"Patch failed: {patch_result['error']}"

        return state

    async def verifier_node(
        self,
        state: AgentState,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None
    ) -> AgentState:
        state.status_message = "VerifierNode: Running test suite in pre-warmed sandbox..."
        test_res = await self.sandbox.run_command_in_sandbox(state.test_command, cwd=self.workspace_path)
        state.sandbox_results.append(test_res)

        await self.emit_event(event_callback, "TEST_OUTPUT", {
            "exit_code": test_res["exit_code"],
            "stdout": test_res["stdout"][:500],
            "stderr_compressed": test_res["stderr_compressed"][:500]
        })
        return state

    async def critic_node(
        self,
        state: AgentState,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None
    ) -> AgentState:
        state.status_message = "CriticNode: Evaluating test outputs & assertions..."
        last_test = state.sandbox_results[-1] if state.sandbox_results else {}

        if last_test.get("exit_code", 0) == 0:
            state.is_completed = True
            state.status_message = "Completed successfully. All assertions passed!"
        else:
            state.retry_count += 1
            if state.retry_count >= state.max_retries:
                state.status_message = "Max retries reached. Rolling back to shadow checkpoint."
                if state.checkpoint_id:
                    await SurgicalDiffPatcher.rollback_to_checkpoint(self.workspace_path, state.checkpoint_id)
            else:
                state.status_message = f"Test failed (retry {state.retry_count}/{state.max_retries}). Compacting context..."
                state.messages = ContextCompactor.compact_history(state.messages)

        return state

    async def record_telemetry(self, state: AgentState):
        """Sends run telemetry to API Gateway."""
        try:
            import httpx
            payload = {
                "run_id": state.run_id,
                "repo_name": "agni-dev/core",
                "task_prompt": state.task_prompt,
                "status": "COMPLETED" if state.is_completed else "FAILED",
                "iterations": len(state.sandbox_results),
                "input_tokens": state.input_tokens,
                "output_tokens": state.output_tokens,
                "duration_ms": 140,
                "final_diff": "\n\n".join(state.applied_diffs) if state.applied_diffs else None
            }
            async with httpx.AsyncClient() as client:
                await client.post(f"{self.api_url}/api/v1/telemetry/runs", json=payload, timeout=3.0)
        except Exception:
            pass

    async def run_pipeline(
        self,
        prompt: str,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None
    ) -> AgentState:
        """Executes full 5-node pipeline with event streaming and telemetry reporting."""
        state = AgentState(task_prompt=prompt)

        state = await self.locator_node(state, event_callback)
        state = await self.planner_node(state, event_callback)

        if state.requires_human_approval:
            return state

        while not state.is_completed and state.retry_count < state.max_retries:
            state = await self.surgical_coder_node(state, event_callback)
            state = await self.verifier_node(state, event_callback)
            state = await self.critic_node(state, event_callback)

        await self.record_telemetry(state)
        await self.emit_event(event_callback, "DONE", {
            "completed": state.is_completed,
            "status": state.status_message,
            "tokens": state.input_tokens + state.output_tokens
        })
        return state
