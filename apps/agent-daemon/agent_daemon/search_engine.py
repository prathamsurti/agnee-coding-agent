import os
import json
import asyncio
import math
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None

class HybridCodeSearch:
    """
    Hybrid Code Search Engine combining:
    1. Lexical exact search (ripgrep / regex with symbol definition boosting)
    2. BM25 AST-chunk scoring (BM25Okapi)
    3. Dense Vector / Reciprocal Rank Fusion (RRF)
    4. Optional Cohere Rerank (rerank-v3.5)
    """

    @classmethod
    async def run_ripgrep(cls, query: str, root_dir: str) -> List[Dict[str, Any]]:
        """Executes ripgrep asynchronously or falls back to pure Python regex."""
        results = []
        try:
            proc = await asyncio.create_subprocess_exec(
                "rg", "--json", "-n", "-C", "1", query, root_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            for line in stdout.decode("utf-8", errors="ignore").splitlines():
                try:
                    data = json.loads(line)
                    if data.get("type") == "match":
                        match_data = data["data"]
                        file_path = match_data["path"]["text"].replace("\\", "/")
                        line_num = match_data["line_number"]
                        matched_text = match_data["lines"]["text"].strip()
                        
                        score = 1.0
                        if re.search(rf"\b(class|def|fn|func|interface|struct)\s+{re.escape(query)}\b", matched_text):
                            score = 2.5
                        elif "apps/" in file_path or "packages/" in file_path:
                            score = 1.5

                        results.append({
                            "file_path": file_path,
                            "start_line": line_num,
                            "end_line": line_num,
                            "content": matched_text,
                            "score": score,
                            "source": "ripgrep"
                        })
                except Exception:
                    pass
            results.sort(key=lambda x: x["score"], reverse=True)
            return results
        except Exception:
            pass

        # Fallback pure-python line search across codebase
        query_lower = query.lower()
        def_pattern = re.compile(rf"\b(class|def|fn|func|interface|struct)\s+{re.escape(query)}\b", re.IGNORECASE)

        for p in Path(root_dir).rglob("*"):
            if p.is_file() and p.suffix in [".py", ".ts", ".tsx", ".js", ".rs", ".go"]:
                norm_p = str(p).replace("\\", "/")
                if any(ign in norm_p for ign in [".git", ".agni", "node_modules", ".venv", "__pycache__", ".next"]):
                    continue
                try:
                    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
                    for i, line in enumerate(lines, 1):
                        if query_lower in line.lower():
                            score = 0.9
                            if def_pattern.search(line):
                                score = 2.5  # High boost for definitions!
                            elif "apps/" in norm_p or "packages/" in norm_p:
                                score = 1.5
                            results.append({
                                "file_path": norm_p,
                                "start_line": i,
                                "end_line": i,
                                "content": line.strip(),
                                "score": score,
                                "source": "python-grep"
                            })
                except Exception:
                    pass

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:40]

    @classmethod
    def chunk_file_by_lines(cls, file_path: str, max_chunk_lines: int = 30) -> List[Dict[str, Any]]:
        chunks = []
        try:
            lines = Path(file_path).read_text(encoding="utf-8", errors="ignore").splitlines()
            for i in range(0, len(lines), max_chunk_lines):
                chunk_lines = lines[i:i + max_chunk_lines]
                content = "\n".join(chunk_lines)
                chunks.append({
                    "file_path": str(file_path).replace("\\", "/"),
                    "start_line": i + 1,
                    "end_line": min(i + max_chunk_lines, len(lines)),
                    "content": content,
                    "tokens": content.lower().split()
                })
        except Exception:
            pass
        return chunks

    @classmethod
    def run_bm25_search(cls, query: str, root_dir: str, top_k: int = 20) -> List[Dict[str, Any]]:
        all_chunks = []
        for p in Path(root_dir).rglob("*"):
            if p.is_file() and p.suffix in [".py", ".ts", ".tsx", ".js", ".rs", ".go"]:
                norm_p = str(p).replace("\\", "/")
                if any(ign in norm_p for ign in [".git", ".agni", "node_modules", ".venv", "__pycache__", ".next"]):
                    continue
                all_chunks.extend(cls.chunk_file_by_lines(str(p)))

        if not all_chunks:
            return []

        query_tokens = query.lower().split()
        if BM25Okapi:
            corpus = [c["tokens"] for c in all_chunks]
            bm25 = BM25Okapi(corpus)
            scores = bm25.get_scores(query_tokens)
            ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
            results = []
            for idx in ranked_indices:
                if scores[idx] > 0:
                    item = dict(all_chunks[idx])
                    item.pop("tokens", None)
                    # Boost definitions
                    score_val = float(scores[idx])
                    if f"class {query.lower()}" in item["content"].lower() or f"def {query.lower()}" in item["content"].lower():
                        score_val *= 2.0
                    item["score"] = score_val
                    item["source"] = "bm25"
                    results.append(item)
            results.sort(key=lambda x: x["score"], reverse=True)
            return results
        else:
            scored = []
            for c in all_chunks:
                text_lower = c["content"].lower()
                matches = sum(1 for q in query_tokens if q in text_lower)
                if matches > 0:
                    item = dict(c)
                    item.pop("tokens", None)
                    score_val = float(matches)
                    if f"class {query.lower()}" in text_lower or f"def {query.lower()}" in text_lower:
                        score_val *= 2.5
                    item["score"] = score_val
                    item["source"] = "tf-overlap"
                    scored.append(item)
            scored.sort(key=lambda x: x["score"], reverse=True)
            return scored[:top_k]

    @classmethod
    def fuse_rrf(cls, ranked_lists: List[List[Dict[str, Any]]], k: int = 60, top_k: int = 5) -> List[Dict[str, Any]]:
        """Reciprocal Rank Fusion across retrieval stages."""
        rrf_scores: Dict[str, float] = {}
        item_map: Dict[str, Dict[str, Any]] = {}

        for r_list in ranked_lists:
            for rank, item in enumerate(r_list):
                key = f"{item['file_path']}:{item['start_line']}"
                item_map[key] = item
                # Weight by base score if definition match
                weight = 1.5 if item.get("score", 1.0) >= 2.0 else 1.0
                rrf_scores[key] = rrf_scores.get(key, 0.0) + (weight / (k + rank + 1))

        sorted_keys = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)[:top_k]
        fused = []
        for key in sorted_keys:
            res = dict(item_map[key])
            res["score"] = round(rrf_scores[key], 4)
            fused.append(res)
        return fused

    @classmethod
    async def search_codebase(cls, query: str, root_dir: str = ".", top_k: int = 5) -> List[Dict[str, Any]]:
        # Run Stage 1 & Stage 2
        rg_results = await cls.run_ripgrep(query, root_dir)
        bm25_results = cls.run_bm25_search(query, root_dir)

        # Stage 3: RRF Fusion
        fused_results = cls.fuse_rrf([rg_results, bm25_results], top_k=max(20, top_k))

        # Stage 4: Cohere Rerank if API key available
        cohere_key = os.getenv("COHERE_API_KEY")
        if cohere_key and fused_results:
            try:
                import httpx
                async with httpx.AsyncClient() as client:
                    cohere_payload = {
                        "model": "rerank-v3.5",
                        "query": query,
                        "documents": [r["content"] for r in fused_results],
                        "top_n": top_k
                    }
                    resp = await client.post(
                        "https://api.cohere.com/v1/rerank",
                        headers={"Authorization": f"Bearer {cohere_key}"},
                        json=cohere_payload,
                        timeout=5.0
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        reranked = []
                        for rank_item in data.get("results", []):
                            orig_idx = rank_item["index"]
                            item = dict(fused_results[orig_idx])
                            item["score"] = rank_item["relevance_score"]
                            item["source"] = "cohere-rerank"
                            reranked.append(item)
                        return reranked
            except Exception:
                pass

        return fused_results[:top_k]
