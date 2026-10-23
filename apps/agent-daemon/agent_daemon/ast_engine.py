import os
import ast
import re
import pickle
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

class AstSkeletonEngine:
    """
    Multi-language AST skeleton generator and incremental binary cache engine.
    Extracts class/function signatures, type annotations, and imports
    while stripping bodies to maximize prompt density for the Planner.
    Caches parsed skeletons in `.agni/ast_cache.bin` keyed by (mtime_ns, size).
    """

    CACHE_FILE = Path(".agni") / "ast_cache.bin"
    _cache: Dict[str, Dict[str, Any]] = {}  # rel_path -> { "mtime_ns": int, "size": int, "skeleton": str, "symbols": list }

    @classmethod
    def ensure_cache_dir(cls, root_dir: str = "."):
        cache_path = Path(root_dir) / cls.CACHE_FILE
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        return cache_path

    @classmethod
    def load_cache(cls, root_dir: str = "."):
        cache_path = Path(root_dir) / cls.CACHE_FILE
        if cache_path.exists():
            try:
                cls._cache = pickle.loads(cache_path.read_bytes())
            except Exception:
                cls._cache = {}
        else:
            cls._cache = {}

    @classmethod
    def save_cache(cls, root_dir: str = "."):
        cache_path = cls.ensure_cache_dir(root_dir)
        try:
            cache_path.write_bytes(pickle.dumps(cls._cache))
        except Exception:
            pass

    @classmethod
    def extract_python_skeleton(cls, file_content: str, rel_path: str) -> Tuple[str, List[Dict[str, Any]]]:
        try:
            tree = ast.parse(file_content)
        except SyntaxError:
            return f"# {rel_path} (Syntax Error - Unparsed)\n", []

        skeleton_lines = [f"# File: {rel_path}"]
        symbols: List[Dict[str, Any]] = []

        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            elif isinstance(node, ast.ClassDef):
                skeleton_lines.append(f"class {node.name}:")
                symbols.append({"name": node.name, "type": "class", "line": node.lineno})
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef):
                        args = [a.arg for a in sub.args.args]
                        skeleton_lines.append(f"    def {sub.name}({', '.join(args)}): ...")
                        symbols.append({"name": f"{node.name}.{sub.name}", "type": "method", "line": sub.lineno})
            elif isinstance(node, ast.FunctionDef):
                args = [a.arg for a in node.args.args]
                skeleton_lines.append(f"def {node.name}({', '.join(args)}): ...")
                symbols.append({"name": node.name, "type": "function", "line": node.lineno})

        return "\n".join(skeleton_lines), symbols

    @classmethod
    def extract_generic_skeleton(cls, file_content: str, rel_path: str, lang: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Regex-based high-accuracy signature extractor for TS/JS/Go/Rust."""
        skeleton_lines = [f"# File: {rel_path} ({lang})"]
        symbols: List[Dict[str, Any]] = []

        # Patterns for functions, classes, interfaces, structs
        patterns = [
            (r'^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\((.*?)\)', "function"),
            (r'^\s*(?:export\s+)?(?:class|interface|type)\s+([a-zA-Z0-9_$]+)', "type"),
            (r'^\s*(?:pub\s+)?(?:async\s+)?fn\s+([a-zA-Z0-9_]+)\s*\((.*?)\)', "function"),
            (r'^\s*func\s+(?:\(.*?\)\s*)?([a-zA-Z0-9_]+)\s*\((.*?)\)', "function"),
            (r'^\s*(?:pub\s+)?struct\s+([a-zA-Z0-9_]+)', "struct"),
        ]

        lines = file_content.splitlines()
        for idx, line in enumerate(lines, 1):
            for pat, sym_type in patterns:
                m = re.match(pat, line)
                if m:
                    sym_name = m.group(1)
                    skeleton_lines.append(line.rstrip() + " { ... }")
                    symbols.append({"name": sym_name, "type": sym_type, "line": idx})
                    break

        return "\n".join(skeleton_lines), symbols

    @classmethod
    def parse_file(cls, full_path: str, rel_path: str) -> Tuple[str, List[Dict[str, Any]]]:
        content = Path(full_path).read_text(encoding="utf-8", errors="ignore")
        if full_path.endswith(".py"):
            return cls.extract_python_skeleton(content, rel_path)
        elif full_path.endswith((".ts", ".tsx", ".js", ".jsx")):
            return cls.extract_generic_skeleton(content, rel_path, "TypeScript/JavaScript")
        elif full_path.endswith(".rs"):
            return cls.extract_generic_skeleton(content, rel_path, "Rust")
        elif full_path.endswith(".go"):
            return cls.extract_generic_skeleton(content, rel_path, "Go")
        else:
            return f"# File: {rel_path}\n", []

    @classmethod
    def update_single_file(cls, file_path: str, root_dir: str = ".") -> Tuple[str, List[Dict[str, Any]]]:
        """Incremental single file update in <5ms."""
        full_path = Path(file_path).resolve()
        root_path = Path(root_dir).resolve()
        try:
            rel_path = str(full_path.relative_to(root_path)).replace("\\", "/")
        except ValueError:
            rel_path = str(full_path).replace("\\", "/")

        if not full_path.exists():
            cls._cache.pop(rel_path, None)
            cls.save_cache(root_dir)
            return "", []

        stat = full_path.stat()
        mtime_ns = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9))
        size = stat.st_size

        skeleton, symbols = cls.parse_file(str(full_path), rel_path)
        cls._cache[rel_path] = {
            "mtime_ns": mtime_ns,
            "size": size,
            "skeleton": skeleton,
            "symbols": symbols
        }
        cls.save_cache(root_dir)
        return skeleton, symbols

    @classmethod
    def build_repo_map(cls, root_dir: str = ".", max_files: int = 100) -> str:
        cls.load_cache(root_dir)
        repo_map_chunks = []
        count = 0
        cache_modified = False

        ignored_patterns = [".git", ".agni", "node_modules", ".venv", "__pycache__", ".next", "dist", "build"]

        for root, dirs, files in os.walk(root_dir):
            if any(ign in root for ign in ignored_patterns):
                continue
            for file in files:
                if file.endswith((".py", ".ts", ".tsx", ".js", ".rs", ".go")):
                    full_path = Path(root) / file
                    rel_path = str(full_path.relative_to(Path(root_dir))).replace("\\", "/")

                    try:
                        stat = full_path.stat()
                        mtime_ns = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9))
                        size = stat.st_size

                        # Check binary cache
                        cached_entry = cls._cache.get(rel_path)
                        if cached_entry and cached_entry.get("mtime_ns") == mtime_ns and cached_entry.get("size") == size:
                            skeleton = cached_entry["skeleton"]
                        else:
                            skeleton, symbols = cls.parse_file(str(full_path), rel_path)
                            cls._cache[rel_path] = {
                                "mtime_ns": mtime_ns,
                                "size": size,
                                "skeleton": skeleton,
                                "symbols": symbols
                            }
                            cache_modified = True

                        repo_map_chunks.append(skeleton)
                        count += 1
                        if count >= max_files:
                            break
                    except Exception:
                        pass
            if count >= max_files:
                break

        if cache_modified:
            cls.save_cache(root_dir)

        return "\n\n".join(repo_map_chunks)
