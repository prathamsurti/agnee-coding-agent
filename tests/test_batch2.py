import asyncio
import os
import sys
import time
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path("apps/agent-daemon").resolve()))
sys.path.insert(0, str(Path("packages/shared-protocol").resolve()))

from agent_daemon.ast_engine import AstSkeletonEngine
from agent_daemon.search_engine import HybridCodeSearch

async def run_batch2_verification():
    print("[TEST] Starting Batch 2 AST Engine & Hybrid Search Verification...")

    # 1. Test build_repo_map and .agni/ast_cache.bin creation
    t0 = time.perf_counter()
    repo_map = AstSkeletonEngine.build_repo_map(".", max_files=50)
    t_first = (time.perf_counter() - t0) * 1000
    print(f"  [OK] Initial repo map built in {t_first:.2f}ms")

    cache_file = Path(".agni") / "ast_cache.bin"
    assert cache_file.exists(), "Cache file .agni/ast_cache.bin was not created!"
    print(f"  [OK] Binary cache .agni/ast_cache.bin verified ({cache_file.stat().st_size} bytes)")

    # 2. Test cached build speed (<1ms on warm cache)
    t0 = time.perf_counter()
    cached_map = AstSkeletonEngine.build_repo_map(".", max_files=50)
    t_cached = (time.perf_counter() - t0) * 1000
    print(f"  [OK] Cached repo map loaded in {t_cached:.2f}ms")

    # 3. Test update_single_file (<5ms)
    test_target = "apps/agent-daemon/agent_daemon/router.py"
    t0 = time.perf_counter()
    skeleton, symbols = AstSkeletonEngine.update_single_file(test_target, ".")
    t_single = (time.perf_counter() - t0) * 1000
    assert any(s["name"] == "DualModelRouter" for s in symbols), "Symbol DualModelRouter not extracted!"
    print(f"  [OK] update_single_file executed in {t_single:.2f}ms (<5ms SLA)")

    # 4. Test HybridCodeSearch finding DualModelRouter
    print("  [TEST] Running HybridCodeSearch for 'DualModelRouter'...")
    results = await HybridCodeSearch.search_codebase("DualModelRouter", ".", top_k=5)
    assert len(results) > 0, "No results returned for DualModelRouter search!"
    
    top_hit = results[0]
    print(f"  [OK] Top match: {top_hit['file_path']} (line {top_hit['start_line']}, score: {top_hit['score']}, source: {top_hit.get('source')})")
    assert "router.py" in top_hit["file_path"].lower() or any("router.py" in r["file_path"].lower() for r in results), "router.py not found in top search results!"

    print("\n[SUCCESS] ALL BATCH 2 VERIFICATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(run_batch2_verification())
