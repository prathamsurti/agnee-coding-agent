import re
import ast
from typing import Tuple, Optional

class SurgicalDiffPatcher:
    """
    3-Stage Deterministic Fuzzy Search/Replace Patcher:
    1. Exact Match
    2. Line-Trimmed Match
    3. Indentation-Normalized Match
    Includes in-memory AST syntax validation to reject broken code before touching disk.
    """

    SEARCH_REPLACE_REGEX = re.compile(
        r"<<<< SEARCH\s*\n(.*?)\n====\s*\n(.*?)\n>>>> REPLACE",
        re.DOTALL
    )

    @classmethod
    def parse_blocks(cls, diff_text: str):
        return cls.SEARCH_REPLACE_REGEX.findall(diff_text)

    @classmethod
    def apply_patch(cls, original_content: str, search_block: str, replace_block: str) -> Tuple[bool, str, Optional[str]]:
        # Stage 1: Exact Match
        if search_block in original_content:
            patched = original_content.replace(search_block, replace_block, 1)
            is_valid, err = cls.validate_syntax(patched)
            if not is_valid:
                return False, original_content, f"AST Syntax error after exact match: {err}"
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
            is_valid, err = cls.validate_syntax(patched)
            if not is_valid:
                return False, original_content, f"AST Syntax error after line-trimmed match: {err}"
            return True, patched, None

        # Stage 3: Indentation-Normalized Match
        search_stripped = [line.strip() for line in search_block.splitlines() if line.strip()]
        for i in range(len(orig_lines) - len(search_stripped) + 1):
            window_stripped = [orig_lines[i + j].strip() for j in range(len(search_stripped)) if orig_lines[i + j].strip()]
            if window_stripped == search_stripped:
                matched_idx = i
                break

        if matched_idx != -1:
            # Detect original indentation of first line
            orig_indent = orig_lines[matched_idx][:len(orig_lines[matched_idx]) - len(orig_lines[matched_idx].lstrip())]
            reindented_replace = []
            for r_line in replace_lines:
                if r_line.strip():
                    reindented_replace.append(orig_indent + r_line.lstrip())
                else:
                    reindented_replace.append("")
            new_lines = orig_lines[:matched_idx] + reindented_replace + orig_lines[matched_idx + len(search_stripped):]
            patched = "\n".join(new_lines)
            is_valid, err = cls.validate_syntax(patched)
            if not is_valid:
                return False, original_content, f"AST Syntax error after indentation-normalized match: {err}"
            return True, patched, None

        return False, original_content, "Search block could not be located in original content"

    @staticmethod
    def validate_syntax(code_content: str, filename: str = "snippet.py") -> Tuple[bool, Optional[str]]:
        if filename.endswith(".py"):
            try:
                ast.parse(code_content)
                return True, None
            except SyntaxError as e:
                return False, f"Line {e.lineno}: {e.msg}"
        return True, None
