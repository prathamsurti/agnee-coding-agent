import asyncio
import os
from pathlib import Path
from typing import Optional, Callable
from .ast_engine import AstSkeletonEngine

class IncrementalRepoWatcher:
    """
    Background file watcher using watchfiles.awatch (<5ms latency)
    to automatically update AST skeletons and the index as the user or agent edits files.
    """

    def __init__(self, root_dir: str = ".", on_change_callback: Optional[Callable[[str], None]] = None):
        self.root_dir = root_dir
        self.on_change_callback = on_change_callback
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def is_ignored(self, path_str: str) -> bool:
        normalized = path_str.replace("\\", "/")
        ignored = [".git", ".agni", "node_modules", ".venv", "__pycache__", ".next", "dist", "build"]
        return any(f"/{ign}/" in normalized or normalized.endswith(f"/{ign}") for ign in ignored)

    async def _watch_loop(self):
        try:
            import watchfiles
            async for changes in watchfiles.awatch(self.root_dir):
                if not self._running:
                    break
                for change_type, file_path in changes:
                    if self.is_ignored(file_path):
                        continue
                    if file_path.endswith((".py", ".ts", ".tsx", ".js", ".rs", ".go")):
                        # Update single file in <5ms
                        AstSkeletonEngine.update_single_file(file_path, self.root_dir)
                        if self.on_change_callback:
                            try:
                                self.on_change_callback(file_path)
                            except Exception:
                                pass
        except ImportError:
            # Fallback simple polling loop
            last_mtimes = {}
            while self._running:
                await asyncio.sleep(1.0)
                for p in Path(self.root_dir).rglob("*"):
                    if p.is_file() and p.suffix in [".py", ".ts", ".tsx", ".js", ".rs", ".go"]:
                        if self.is_ignored(str(p)):
                            continue
                        try:
                            mtime = p.stat().st_mtime
                            if p in last_mtimes and last_mtimes[p] != mtime:
                                AstSkeletonEngine.update_single_file(str(p), self.root_dir)
                                if self.on_change_callback:
                                    self.on_change_callback(str(p))
                            last_mtimes[p] = mtime
                        except Exception:
                            pass

    def start(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._watch_loop())

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
