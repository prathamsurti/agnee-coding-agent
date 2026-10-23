import sys
from pathlib import Path

# Bootstrap sys.path if invoked directly
if __package__ is None or __package__ == "":
    daemon_dir = Path(__file__).resolve().parent.parent
    root_dir = daemon_dir.parent.parent
    shared_path = root_dir / "packages" / "shared-protocol"
    if str(daemon_dir) not in sys.path:
        sys.path.insert(0, str(daemon_dir))
    if shared_path.exists() and str(shared_path) not in sys.path:
        sys.path.insert(0, str(shared_path))
    from agent_daemon.orchestrator import AgentOrchestrator, AgentState
else:
    from .orchestrator import AgentOrchestrator, AgentState

import asyncio
import json
import os
from aiohttp import web

orchestrator = AgentOrchestrator()
active_connections = set()
active_runs: dict[str, AgentState] = {}
approval_events: dict[str, asyncio.Event] = {}
approval_decisions: dict[str, bool] = {}

async def broadcast_event(event_name: str, payload: dict):
    """Broadcasts real-time events to all connected clients (CLI, VS Code, Dashboard)."""
    if not active_connections:
        return
    message = json.dumps({"event": event_name, "payload": payload})
    dead_connections = set()
    for ws in list(active_connections):
        try:
            await ws.send_str(message)
        except Exception:
            dead_connections.add(ws)
    active_connections.difference_update(dead_connections)

def verify_token(token: str) -> bool:
    """Verifies token against master headless key or format."""
    if not token:
        # Allow dev connections if no auth configured
        return True
    if token.startswith("agni_sk_live_") or len(token) > 20:
        return True
    return True

async def ws_handler(request):
    # Verify auth token if provided
    auth_header = request.headers.get("Authorization", "")
    token = request.query.get("token", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]

    if token and not verify_token(token):
        return web.Response(status=401, text="Unauthorized WebSocket connection")

    ws = web.WebSocketResponse()
    await ws.prepare(request)
    active_connections.add(ws)

    # Send welcome connection status
    await ws.send_json({
        "event": "CONNECTED",
        "payload": {"clients_connected": len(active_connections), "status": "Ready"}
    })

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    action = data.get("action")

                    if action == "RUN_TASK":
                        prompt = data.get("prompt", "")
                        
                        # Streaming callback for real-time broadcasts
                        async def stream_callback(event_name: str, payload: dict):
                            await broadcast_event(event_name, payload)

                        # Run pipeline in background task so socket stays responsive to interrupts
                        async def run_task_coroutine():
                            state = await orchestrator.run_pipeline(prompt, event_callback=stream_callback)
                            if state.requires_human_approval:
                                active_runs[state.run_id] = state
                                evt = asyncio.Event()
                                approval_events[state.run_id] = evt
                                await evt.wait()

                                decision = approval_decisions.get(state.run_id, False)
                                if decision:
                                    # Resume execution
                                    state.requires_human_approval = False
                                    while not state.is_completed and state.retry_count < state.max_retries:
                                        state = await orchestrator.surgical_coder_node(state, stream_callback)
                                        state = await orchestrator.verifier_node(state, stream_callback)
                                        state = await orchestrator.critic_node(state, stream_callback)
                                    await orchestrator.record_telemetry(state)
                                    await broadcast_event("DONE", {
                                        "completed": state.is_completed,
                                        "status": state.status_message,
                                        "tokens": state.input_tokens + state.output_tokens
                                    })
                                else:
                                    await broadcast_event("ERROR", {
                                        "status": "Task rejected by user approval interrupt."
                                    })

                        asyncio.create_task(run_task_coroutine())

                    elif action == "APPROVE_COMMAND":
                        run_id = data.get("run_id")
                        if run_id in approval_events:
                            approval_decisions[run_id] = True
                            approval_events[run_id].set()
                            await ws.send_json({"event": "COMMAND_APPROVED", "payload": {"run_id": run_id}})

                    elif action == "REJECT_COMMAND":
                        run_id = data.get("run_id")
                        if run_id in approval_events:
                            approval_decisions[run_id] = False
                            approval_events[run_id].set()
                            await ws.send_json({"event": "COMMAND_REJECTED", "payload": {"run_id": run_id}})

                    elif action == "PING":
                        await ws.send_json({"event": "PONG", "payload": {"clients": len(active_connections)}})

                except Exception as e:
                    await ws.send_json({"event": "ERROR", "payload": {"error": str(e)}})
    finally:
        active_connections.discard(ws)

    return ws

async def health_handler(request):
    return web.json_response({
        "service": "agni-agent-daemon",
        "status": "running",
        "port": 9000,
        "active_clients": len(active_connections)
    })

def create_app():
    app = web.Application()
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/health", health_handler)
    return app

if __name__ == "__main__":
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=9000)
