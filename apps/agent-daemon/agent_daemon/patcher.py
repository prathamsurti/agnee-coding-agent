import os
import re
import ast
import difflib
import shutil
import time
import asyncio
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, List

class SurgicalDiffPatcher:
    """
    3-Stage Deterministic Fuzzy Search/Replace Patcher:
    1. Exact Match
    2. Line-Trimmed Match
    3. Indentation-Normalized Match
    Features in-memory AST syntax validation, Git/Local shadow checkpoints,
    and atomic disk patching with unified diff generation.
    """

    SEARCH_REPLACE_REGEX = re.compile(
        r"<<<< SEARCH\s*\n(.*?)\n====\s*\n(.*?)\n>>>> REPLACE",
        re.DOTALL
    )

    @classmethod
    def parse_blocks(cls, diff_text: str) -> List[Tuple[str, str]]:
        return cls.SEARCH_REPLACE_REGEX.findall(diff_text)

    @classmethod
    def validate_syntax(cls, code_content: str, filename: str = "snippet.py") -> Tuple[bool, Optional[str]]:
        if filename.endswith(".py"):
            try:
                ast.parse(code_content)
                return True, None
            except SyntaxError as e:
                return False, f"Python SyntaxError at line {e.lineno}: {e.msg}"
        
        # Balanced delimiter validation for JS/TS/Go/Rust
        if filename.endswith((".ts", ".tsx", ".js", ".jsx", ".rs", ".go")):
            brackets = {'(': ')', '{': '}', '[': ']'}
            stack = []
            for line_no, line in enumerate(code_content.splitlines(), 1):
                # Basic quote stripping
                cleaned = re.sub(r'".*?"|\'.*?\'|`.*?`', '', line)
                for char in cleaned:
                    if char in brackets:
                        stack.append((char, line_no))
                    elif char in brackets.values():
                        if not stack:
                            return False, f"Unmatched closing '{char}' at line {line_no}"
                        top, top_line = stack.pop()
                        if brackets[top] != char:
                            return False, f"Mismatched '{top}' (line {top_line}) with '{char}' at line {line_no}"
            if stack:
                top, top_line = stack[-1]
                return False, f"Unclosed '{top}' from line {top_line}"

        return True, None

    @classmethod
    def apply_single_block(cls, original_content: str, search_block: str, replace_block: str) -> Tuple[bool, str, Optional[str]]:
        # Stage 1: Exact Match
        if search_block in original_content:
            patched = original_content.replace(search_block, replace_block, 1)
            return True, patched, None

        # Stage 2: Line-Trimmed Match
        orig_lines = original_content.splitlines()
        search_lines = [line.rstrip() for line in search_block.splitlines()]
        replace_lines = replace_block.splitlines()

        matched_idx = -1
        for i in range(len(orig_lines) - len(search_lines) + 1):
            window = [orig_lines[i + j].rstrip() for j in range(len(search_lines))]
            if window == search_lines:
                matched_idx = i
                break

        if matched_idx != -1:
            new_lines = orig_lines[:matched_idx] + replace_lines + orig_lines[matched_idx + len(search_lines):]
            patched = "\n".join(new_lines)
            return True, patched, None

        # Stage 3: Indentation-Normalized Match
        search_stripped = [line.strip() for line in search_block.splitlines() if line.strip()]
        for i in range(len(orig_lines) - len(search_stripped) + 1):
            window_stripped = [orig_lines[i + j].strip() for j in range(len(search_stripped)) if orig_lines[i + j].strip()]
            if window_stripped == search_stripped:
                matched_idx = i
                break

        if matched_idx != -1:
            orig_indent = orig_lines[matched_idx][:len(orig_lines[matched_idx]) - len(orig_lines[matched_idx].lstrip())]
            reindented_replace = []
            for r_line in replace_lines:
                if r_line.strip():
                    reindented_replace.append(orig_indent + r_line.lstrip())
                else:
                    reindented_replace.append("")
            new_lines = orig_lines[:matched_idx] + reindented_replace + orig_lines[matched_idx + len(search_stripped):]
            patched = "\n".join(new_lines)
            return True, patched, None

        return False, original_content, "Search block could not be located in original content"

    @classmethod
    async def create_git_checkpoint(cls, workspace_path: str = ".") -> Optional[str]:
        """Creates a Git shadow stash or fallback local file backup."""
        # Check Git first
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "stash", "create",
                cwd=workspace_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
            sha = stdout.decode().strip()
            if sha:
                return f"git:{sha}"
        except Exception:
            pass

        # Fallback local shadow checkpoint directory
        cp_id = f"local:{int(time.time() * 1000)}"
        cp_dir = Path(workspace_path) / ".agni" / "checkpoints" / cp_id.split(":")[1]
        cp_dir.mkdir(parents=True, exist_ok=True)
        return cp_id

    @classmethod
    async def rollback_to_checkpoint(cls, workspace_path: str, checkpoint_id: str) -> bool:
        """Rolls back files to previous checkpoint."""
        if not checkpoint_id:
            return False

        if checkpoint_id.startswith("git:"):
            sha = checkpoint_id.split(":")[1]
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git", "read-tree", "--reset", "-u", sha,
                    cwd=workspace_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await asyncio.wait_for(proc.communicate(), timeout=3.0)
                return proc.returncode == 0
            except Exception:
                return False

        elif checkpoint_id.startswith("local:"):
            cp_dir = Path(workspace_path) / ".agni" / "checkpoints" / checkpoint_id.split(":")[1]
            if cp_dir.exists():
                for backup_file in cp_dir.rglob("*"):
                    if backup_file.is_file():
                        rel = backup_file.relative_to(cp_dir)
                        target = Path(workspace_path) / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup_file, target)
                return True
        return False

    @classmethod
    async def apply_surgical_diff(cls, workspace_path: str, rel_file_path: str, diff_text: str) -> Dict[str, Any]:
        """
        Parses all blocks, checks syntax, writes atomically to disk, and returns unified diff.
        """
        target_file = Path(workspace_path) / rel_file_path
        if not target_file.exists():
            return {
                "success": False,
                "error": f"Target file does not exist: {rel_file_path}",
                "blocks_applied": 0,
                "unified_diff": ""
            }

        original_content = target_file.read_text(encoding="utf-8", errors="ignore")
        current_content = original_content

        blocks = cls.parse_blocks(diff_text)
        if not blocks:
            return {
                "success": False,
                "error": "No valid <<<< SEARCH ... ==== ... >>>> REPLACE blocks found in diff text",
                "blocks_applied": 0,
                "unified_diff": ""
            }

        # Backup file to local checkpoint if active
        cp_base = Path(workspace_path) / ".agni" / "checkpoints"
        if cp_base.exists():
            recent_cps = sorted(cp_base.glob("*"), key=os.path.getmtime, reverse=True)
            if recent_cps:
                backup_dest = recent_cps[0] / rel_file_path
                backup_dest.parent.mkdir(parents=True, exist_ok=True)
                if not backup_dest.exists():
                    shutil.copy2(target_file, backup_dest)

        applied_count = 0
        for search_block, replace_block in blocks:
            matched, new_content, err = cls.apply_single_block(current_content, search_block, replace_block)
            if not matched:
                return {
                    "success": False,
                    "error": f"Failed applying block {applied_count + 1}: {err}",
                    "blocks_applied": applied_count,
                    "unified_diff": ""
                }
            current_content = new_content
            applied_count += 1

        # Validate syntax before touching disk
        is_valid, syntax_err = cls.validate_syntax(current_content, rel_file_path)
        if not is_valid:
            return {
                "success": False,
                "error": f"AST syntax validation failed: {syntax_err}",
                "blocks_applied": 0,
                "unified_diff": ""
            }

        # Write atomically using a temporary file
        temp_file = target_file.with_suffix(f"{target_file.suffix}.tmp")
        temp_file.write_text(current_content, encoding="utf-8")
        temp_file.replace(target_file)

        # Generate standard unified diff
        diff_lines = difflib.unified_diff(
            original_content.splitlines(keepends=True),
            current_content.splitlines(keepends=True),
            fromfile=f"a/{rel_file_path}",
            tofile=f"b/{rel_file_path}"
        )
        unified_diff_str = "".join(diff_lines)

        return {
            "success": True,
            "error": None,
            "blocks_applied": applied_count,
            "unified_diff": unified_diff_str
        }
