import asyncio
import json
from aiohttp import web
from .orchestrator import AgentOrchestrator

orchestrator = AgentOrchestrator()

async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    async for msg in ws:
        if msg.type == web.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
                action = data.get("action")
                
                if action == "RUN_TASK":
                    prompt = data.get("prompt", "")
                    await ws.send_json({"event": "PLAN_CREATED", "payload": {"status": "Starting pipeline", "prompt": prompt}})
                    
                    state = await orchestrator.run_pipeline(prompt)
                    
                    await ws.send_json({"event": "DIFF_APPLIED", "payload": {"diffs": state.applied_diffs}})
                    await ws.send_json({"event": "TEST_OUTPUT", "payload": {"sandbox": state.sandbox_results}})
                    await ws.send_json({"event": "DONE", "payload": {"completed": state.is_completed, "msg": state.status_message}})
                else:
                    await ws.send_json({"event": "PONG", "payload": {"message": "Daemon alive"}})
            except Exception as e:
                await ws.send_json({"event": "ERROR", "payload": {"error": str(e)}})
    return ws

async def health_handler(request):
    return web.json_response({"service": "agni-agent-daemon", "status": "running", "port": 9000})

def create_app():
    app = web.Application()
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/health", health_handler)
    return app

if __name__ == "__main__":
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=9000)
