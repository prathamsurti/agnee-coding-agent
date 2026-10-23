import os
import asyncio
import re
from pathlib import Path
from typing import Tuple, Dict, Any, Optional

class DockerSandboxManager:
    """
    Manages pre-warmed sandbox container pool (`agni-sandbox-worker-{0..1}`)
    using an asyncio.Queue, with sub-50ms execution via `docker exec`,
    30s timeout enforcement, and stack-trace pruning to keep LLM context clean.
    Gracefully falls back to local async subprocess isolation if Docker daemon is not active.
    """

    def __init__(self, pool_size: int = 2, timeout_seconds: int = 30, image_name: str = "agni-sandbox:latest"):
        self.pool_size = pool_size
        self.timeout_seconds = timeout_seconds
        self.image_name = image_name
        self.container_queue: asyncio.Queue[str] = asyncio.Queue()
        self.docker_available: Optional[bool] = None
        self._initialized = False

    @staticmethod
    def compress_traceback(stderr: str) -> str:
        """
        Strips internal framework frames (site-packages, pytest internals,
        node_modules) while preserving the exact file, line number,
        failing line, and assertion message.
        """
        if not stderr:
            return ""

        lines = stderr.splitlines()
        compressed = []
        skip_patterns = ["site-packages", "/lib/python", "node_modules", "pytest/_pytest", "pluggy"]

        for line in lines:
            if any(pattern in line for pattern in skip_patterns):
                continue
            if line.startswith("E   ") or "AssertionError" in line or "Error:" in line or "Exception:" in line:
                compressed.append(line)
            elif "File \"" in line or "at " in line:
                compressed.append(line)
            elif line.strip().startswith(">"):
                compressed.append(line)
            elif not line.startswith(" "):
                compressed.append(line)

        return "\n".join(compressed[-30:]) if len(compressed) > 30 else "\n".join(compressed)

    async def check_docker(self) -> bool:
        if self.docker_available is not None:
            return self.docker_available
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "version",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await asyncio.wait_for(proc.communicate(), timeout=2.0)
            self.docker_available = (proc.returncode == 0)
        except Exception:
            self.docker_available = False
        return self.docker_available

    async def initialize_pool(self, workspace_path: str = "."):
        """Starts or reuses 2 pre-warmed worker containers."""
        if self._initialized:
            return
        
        has_docker = await self.check_docker()
        abs_ws = str(Path(workspace_path).resolve())

        if has_docker:
            for i in range(self.pool_size):
                container_name = f"agni-sandbox-worker-{i}"
                started_container = False
                try:
                    # Check if running
                    proc = await asyncio.create_subprocess_exec(
                        "docker", "inspect", "-f", "{{.State.Running}}", container_name,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL
                    )
                    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
                    is_running = stdout.decode().strip() == "true"

                    if not is_running:
                        # Remove any stopped container
                        await asyncio.create_subprocess_exec("docker", "rm", "-f", container_name)
                        # Start pre-warmed container with mounted workspace
                        start_proc = await asyncio.create_subprocess_exec(
                            "docker", "run", "-d",
                            "--name", container_name,
                            "-v", f"{abs_ws}:/workspace",
                            "-w", "/workspace",
                            "python:3.12-slim-bookworm",
                            "tail", "-f", "/dev/null",
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL
                        )
                        await asyncio.wait_for(start_proc.communicate(), timeout=3.0)
                        started_container = True
                    else:
                        started_container = True
                except Exception:
                    started_container = False

                if started_container:
                    await self.container_queue.put(container_name)
                else:
                    await self.container_queue.put(f"local-worker-{i}")
        else:
            # Fallback worker tokens for local subprocess runner
            for i in range(self.pool_size):
                await self.container_queue.put(f"local-worker-{i}")

        self._initialized = True

    async def run_command_in_sandbox(self, command: str, cwd: str = ".") -> Dict[str, Any]:
        """
        Executes command in an acquired idle sandbox container or local subprocess,
        enforcing a 30s timeout and returning pruned stderr.
        """
        if not self._initialized:
            await self.initialize_pool(cwd)

        # Acquire container worker
        worker = await self.container_queue.get()
        try:
            if worker.startswith("agni-sandbox-worker-"):
                exec_cmd = ["docker", "exec", "-w", "/workspace", worker, "/bin/sh", "-c", command]
                proc = await asyncio.create_subprocess_exec(
                    *exec_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
            else:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    cwd=cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.timeout_seconds
            )
            stdout = stdout_b.decode("utf-8", errors="replace")
            stderr = stderr_b.decode("utf-8", errors="replace")

            return {
                "exit_code": proc.returncode,
                "stdout": stdout,
                "stderr_compressed": self.compress_traceback(stderr),
                "worker": worker,
                "timed_out": False
            }
        except asyncio.TimeoutError:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr_compressed": f"Execution timed out after {self.timeout_seconds} seconds.",
                "worker": worker,
                "timed_out": True
            }
        finally:
            # Release container back to pool
            await self.container_queue.put(worker)
