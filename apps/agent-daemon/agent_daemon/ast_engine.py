import ast
import os
from pathlib import Path
from typing import Dict, List, Any

class AstSkeletonEngine:
    """
    Parses code repositories into high-density symbol skeletons
    (signatures, classes, docstrings, and imports without bodies)
    to minimize prompt token overhead for the Planner node.
    """

    @classmethod
    def extract_python_skeleton(cls, file_content: str, rel_path: str) -> str:
        try:
            tree = ast.parse(file_content)
        except SyntaxError:
            return f"# {rel_path} (Syntax Error - Unparsed)\n"

        skeleton_lines = [f"# File: {rel_path}"]
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                # Keep top-level imports
                continue
            elif isinstance(node, ast.ClassDef):
                skeleton_lines.append(f"class {node.name}:")
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef):
                        args = [a.arg for a in sub.args.args]
                        skeleton_lines.append(f"    def {sub.name}({', '.join(args)}): ...")
            elif isinstance(node, ast.FunctionDef):
                args = [a.arg for a in node.args.args]
                skeleton_lines.append(f"def {node.name}({', '.join(args)}): ...")

        return "\n".join(skeleton_lines)

    @classmethod
    def build_repo_map(cls, root_dir: str, max_files: int = 50) -> str:
        repo_map_chunks = []
        count = 0
        for root, dirs, files in os.walk(root_dir):
            if any(ignored in root for ignored in [".git", "node_modules", ".venv", "__pycache__", ".next"]):
                continue
            for file in files:
                if file.endswith(".py"):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, root_dir)
                    try:
                        content = Path(full_path).read_text(encoding="utf-8", errors="ignore")
                        skeleton = cls.extract_python_skeleton(content, rel_path)
                        repo_map_chunks.append(skeleton)
                        count += 1
                        if count >= max_files:
                            break
                    except Exception:
                        pass
        return "\n\n".join(repo_map_chunks)
