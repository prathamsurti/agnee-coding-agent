import asyncio
import os
import sys
import socket
import platform
import time
import json
from pathlib import Path
import typer
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm

# Bootstrap sys.path for monorepo packages
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
for _p in [
    _REPO_ROOT / "apps" / "agent-daemon",
    _REPO_ROOT / "packages" / "shared-protocol"
]:
    _p_str = str(_p)
    if _p_str not in sys.path:
        sys.path.insert(0, _p_str)
from .auth import (
    get_base_url,
    save_auth_session,
    get_auth_session,
    clear_auth_session,
    get_stored_refresh_token,
    silent_refresh,
    verify_token_locally
)

app = typer.Typer(
    name="agni",
    help="Agni Dev - High Speed Agentic Coding Monorepo CLI",
    add_completion=False
)
console = Console()

@app.command()
def login():
    """Sign in to Agni Dev via RFC 8628 OAuth 2.0 Device Flow."""
    base_url = get_base_url()
    hostname = socket.gethostname()
    os_name = platform.system()

    console.print("[bold cyan][AGNI] Agni Dev - Machine Authentication[/bold cyan]")
    
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task(description="Contacting Agni API Gateway...", total=None)
        try:
            resp = httpx.post(
                f"{base_url}/api/v1/auth/device/init",
                json={
                    "client_type": "CLI",
                    "hostname": hostname,
                    "os_platform": os_name
                },
                timeout=5.0
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            progress.stop()
            console.print(f"[bold red][ERROR] Failed to initiate device flow:[/bold red] {e}")
            raise typer.Exit(1)

    device_code = data["device_code"]
    user_code = data["user_code"]
    verification_uri_complete = data["verification_uri_complete"]
    interval = data.get("interval", 2)

    # Render formatted Rich Panel
    panel_content = (
        f"[bold white]1. Open browser:[/bold white] [bold cyan underline]{verification_uri_complete}[/bold cyan underline]\n"
        f"[bold white]2. Confirm Code:[/bold white] [bold yellow]{user_code}[/bold yellow]\n\n"
        f"[dim]Device: {hostname} ({os_name})[/dim]"
    )
    console.print(Panel(panel_content, title="[bold green]Device Authorization Required[/bold green]", expand=False))

    # Background polling loop
    console.print("[dim]Waiting for authorization in browser (Ctrl+C to abort)...[/dim]")
    start_time = time.time()
    
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        poll_task = progress.add_task(description="Polling auth status...", total=None)
        
        while time.time() - start_time < 300:
            time.sleep(interval)
            try:
                poll_resp = httpx.post(
                    f"{base_url}/api/v1/auth/device/poll",
                    json={"device_code": device_code},
                    timeout=5.0
                )
                if poll_resp.status_code == 200:
                    poll_data = poll_resp.json()
                    status_val = poll_data.get("status")
                    
                    if status_val == "approved":
                        tokens = poll_data["tokens"]
                        save_auth_session(
                            user_email=f"user-{tokens['user_id'][:8]}@agni.dev",
                            workspace_id=tokens["workspace_id"],
                            access_token=tokens["access_token"],
                            refresh_token=tokens["refresh_token"],
                            plan_tier=tokens.get("plan_tier", "FREE")
                        )
                        progress.stop()
                        console.print(f"\n[bold green][OK] Login Successful![/bold green] Session saved to ~/.agni/config.json")
                        return
                    elif status_val == "denied":
                        progress.stop()
                        console.print("\n[bold red][ERROR] Device login was denied by user.[/bold red]")
                        raise typer.Exit(1)
                    elif status_val == "expired":
                        progress.stop()
                        console.print("\n[bold red][ERROR] Authorization session expired. Please run 'agni login' again.[/bold red]")
                        raise typer.Exit(1)
            except Exception:
                pass

    console.print("\n[bold red][ERROR] Device authorization timed out.[/bold red]")

@app.command()
def logout():
    """Log out and remove stored Agni credentials."""
    clear_auth_session()
    console.print("[bold green][OK] Logged out successfully. Local credentials cleared.[/bold green]")

@app.command()
def status():
    """Display current authentication and workspace status."""
    session = get_auth_session()
    if not session or not session.get("access_token"):
        console.print("[yellow][WARN] Not logged in. Run [bold]agni login[/bold] to authenticate.[/yellow]")
        return

    token = session.get("access_token")
    # Sub-millisecond local token verification
    token_valid = True
    try:
        verify_token_locally(token)
    except Exception:
        token_valid = False

    table = Table(title="[AGNI] Agni Dev - Current Session")
    table.add_column("Property", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")

    table.add_row("User Identifier", session.get("user_email", "N/A"))
    table.add_row("Active Workspace", session.get("workspace_id", "N/A"))
    table.add_row("Plan Tier", session.get("plan_tier", "FREE"))
    table.add_row("API Gateway", get_base_url())
    table.add_row("Token Type", "Ed25519 Asymmetric JWT")
    table.add_row("Local JWT Valid", "[green]Verified (<0.2ms)[/green]" if token_valid else "[yellow]Expired (Will auto-refresh)[/yellow]")

    console.print(table)

async def _stream_code_task(prompt: str, token: str, ws_url: str):
    import aiohttp
    last_diff = ""

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(f"{ws_url}?token={token}", timeout=5.0) as ws:
                await ws.send_json({"action": "RUN_TASK", "prompt": prompt})

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        event = data.get("event")
                        payload = data.get("payload", {})

                        if event == "CONNECTED":
                            console.print("[dim][+] Connected to Agni Agent Daemon WebSocket[/dim]")
                        elif event == "FILE_READ":
                            files = payload.get("files", [])
                            console.print(f"[cyan][LOCATOR]:[/cyan] Indexed and read {len(files)} target files: [bold]{', '.join(files)}[/bold]")
                        elif event == "PLAN_CREATED":
                            console.print(f"[magenta][PLANNER]:[/magenta] Plan formulated using [bold]{payload.get('model')}[/bold]")
                            for s in payload.get("plan", []):
                                console.print(f"   [dim]- Step {s.get('step')}: {s.get('action')} on {s.get('file')}[/dim]")
                        elif event == "DIFF_APPLIED":
                            diff_str = payload.get("unified_diff", "")
                            last_diff = diff_str
                            console.print(f"[green][CODER]:[/green] Applied diff ({payload.get('blocks')} blocks)")
                        elif event == "TEST_OUTPUT":
                            ec = payload.get("exit_code")
                            if ec == 0:
                                console.print("[green][VERIFIER]:[/green] Sandbox assertions passed! (Exit code 0)")
                            else:
                                console.print(f"[yellow][VERIFIER]:[/yellow] Test failed (Exit code {ec})")
                        elif event == "HUMAN_APPROVAL_REQUIRED":
                            cmd = payload.get("command")
                            console.print(f"\n[bold red][WARN] HUMAN APPROVAL REQUIRED:[/bold red] Destructive command detected:\n[yellow]{cmd}[/yellow]")
                            approved = Confirm.ask("Do you authorize execution of this command?")
                            if approved:
                                await ws.send_json({"action": "APPROVE_COMMAND", "run_id": payload.get("run_id")})
                            else:
                                await ws.send_json({"action": "REJECT_COMMAND", "run_id": payload.get("run_id")})
                        elif event == "DONE":
                            console.print(f"\n[bold green][OK] Task Completed Successfully![/bold green] Total tokens: {payload.get('tokens')}")
                            if last_diff:
                                console.print(Panel(last_diff, title="[bold blue]Unified Diff Applied[/bold blue]", expand=False))
                            return
                        elif event == "ERROR":
                            console.print(f"\n[bold red][ERROR] Daemon Error:[/bold red] {payload.get('error') or payload.get('status')}")
                            return
    except Exception:
        # Fallback to local embedded AgentOrchestrator
        console.print("[dim]Note: Daemon WebSocket offline; running embedded AgentOrchestrator pipeline...[/dim]")
        from agent_daemon.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator(workspace_path=".")

        async def cli_event_handler(event_name: str, payload: dict):
            if event_name == "FILE_READ":
                console.print(f"[cyan][LOCATOR]:[/cyan] Read target files: [bold]{', '.join(payload.get('files', []))}[/bold]")
            elif event_name == "PLAN_CREATED":
                console.print(f"[magenta][PLANNER]:[/magenta] Formulated execution plan with model {payload.get('model')}")
            elif event_name == "DIFF_APPLIED":
                console.print(f"[green][CODER]:[/green] Applied {payload.get('blocks')} surgical diff block(s)")
            elif event_name == "TEST_OUTPUT":
                console.print(f"[green][VERIFIER]:[/green] Sandbox test exit code: {payload.get('exit_code')}")

        state = await orch.run_pipeline(prompt, event_callback=cli_event_handler)
        console.print(f"\n[bold green][OK] Pipeline Execution Completed![/bold green] Status: {state.status_message}")
        if state.applied_diffs:
            console.print(Panel(state.applied_diffs[-1], title="[bold blue]Unified Diff Applied[/bold blue]", expand=False))

@app.command()
def code(
    prompt: str = typer.Argument(..., help="The coding instruction or feature request"),
    repo: str = typer.Option(".", "--repo", "-r", help="Repository path or identifier")
):
    """Run an autonomous coding agent task on the repository streaming live from the daemon."""
    session = get_auth_session()
    token = session.get("access_token", "dev_token")

    ws_url = os.getenv("AGNI_DAEMON_WS_URL", "ws://localhost:9000/ws")

    console.print(f"[bold cyan][AGNI] Agni Agent Executing Task:[/bold cyan] {prompt}")
    console.print(f"[dim]Daemon WebSocket: {ws_url}[/dim]\n")

    asyncio.run(_stream_code_task(prompt, token, ws_url))

if __name__ == "__main__":
    app()
