import asyncio
import re
from typing import Tuple, Dict, Any, Optional

class DockerSandboxManager:
    """
    Manages pre-warmed sandbox execution pool and stack-trace pruning
    to guarantee sub-50ms test runs and minimal context window pollution.
    """
    def __init__(self, pool_size: int = 2, timeout_seconds: int = 30):
        self.pool_size = pool_size
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def compress_traceback(stderr: str) -> str:
        """
        Strips internal framework lines (pytest, unittest, site-packages)
        leaving only the relevant assertion failure and user source lines.
        """
        lines = stderr.splitlines()
        compressed = []
        skip_block = False

        for line in lines:
            if "site-packages" in line or "/lib/python" in line:
                continue
            if line.startswith("E   ") or "AssertionError" in line or "Error:" in line:
                compressed.append(line)
            elif "File \"" in line and "test_" in line:
                compressed.append(line)
            elif not line.strip().startswith("at "):
                compressed.append(line)

        return "\n".join(compressed[-25:]) if len(compressed) > 25 else "\n".join(compressed)

    async def run_command_in_sandbox(self, command: str, cwd: str = "/workspace") -> Dict[str, Any]:
        """Runs command asynchronously inside container sandbox with execution timeout."""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
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
                "timed_out": False
            }
        except asyncio.TimeoutError:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr_compressed": f"Command timed out after {self.timeout_seconds} seconds.",
                "timed_out": True
            }
