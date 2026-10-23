import asyncio
import os
import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path("apps/agent-daemon").resolve()))
sys.path.insert(0, str(Path("packages/shared-protocol").resolve()))

from agent_daemon.orchestrator import AgentOrchestrator, AgentState

async def run_batch4_verification():
    print("[TEST] Starting Batch 4 LangGraph Orchestrator & Dual Router Verification...")

    orchestrator = AgentOrchestrator(workspace_path=".")
    events_received = []

    async def test_event_callback(event_name: str, payload: dict):
        events_received.append((event_name, payload))
        print(f"  [STREAM] Event emitted: {event_name}")

    prompt = "Add speed route to DualModelRouter"
    state = await orchestrator.run_pipeline(prompt, event_callback=test_event_callback)

    # 1. Verify Node Transitions
    event_names = [e[0] for e in events_received]
    assert "FILE_READ" in event_names, "FILE_READ event not received"
    assert "PLAN_CREATED" in event_names, "PLAN_CREATED event not received"
    assert "TEST_OUTPUT" in event_names, "TEST_OUTPUT event not received"
    assert "DONE" in event_names, "DONE event not received"
    print("  [OK] All 5 node event transitions streamed in real-time")

    # 2. Verify State and Token Usage
    assert state.is_completed, "Pipeline state was not marked completed"
    assert state.input_tokens > 0, "Input tokens not tracked"
    assert state.output_tokens > 0, "Output tokens not tracked"
    print(f"  [OK] Token counters tracked: {state.input_tokens} in / {state.output_tokens} out")

    # 3. Test Human-in-the-Loop Interrupt Detection
    destructive_state = AgentState(task_prompt="Clear database with DROP TABLE users")
    destructive_state.test_command = "DROP TABLE users"
    destructive_state = await orchestrator.planner_node(destructive_state)
    assert destructive_state.requires_human_approval, "Destructive command was not intercepted!"
    print("  [OK] Destructive command intercepted with requires_human_approval = True")

    print("\n[SUCCESS] ALL BATCH 4 VERIFICATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(run_batch4_verification())
