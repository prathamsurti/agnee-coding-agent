import asyncio
import os
import sys
import shutil
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path("apps/agent-daemon").resolve()))
sys.path.insert(0, str(Path("packages/shared-protocol").resolve()))

from agent_daemon.patcher import SurgicalDiffPatcher
from agent_daemon.sandbox import DockerSandboxManager

async def run_batch3_verification():
    print("[TEST] Starting Batch 3 Surgical Patcher & Sandbox Verification...")

    # Create a temporary sandbox target file for diff testing
    test_dir = Path("tests/sandbox_scratch")
    test_dir.mkdir(parents=True, exist_ok=True)
    target_file = test_dir / "calculator.py"

    original_code = (
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n\n"
        "def multiply(a: int, b: int) -> int:\n"
        "    return a * b\n"
    )
    target_file.write_text(original_code, encoding="utf-8")

    # 1. Test Checkpoint Creation
    checkpoint_id = await SurgicalDiffPatcher.create_git_checkpoint("tests/sandbox_scratch")
    assert checkpoint_id is not None, "Failed to create checkpoint"
    print(f"  [OK] Created checkpoint: {checkpoint_id}")

    # 2. Test Syntax Validation Rejection (Malformed Syntax)
    malformed_diff = (
        "<<<< SEARCH\n"
        "def multiply(a: int, b: int) -> int:\n"
        "    return a * b\n"
        "====\n"
        "def multiply(a: int, b: int) -> int:\n"
        "    return a * * * broken syntax !@#$\n"
        ">>>> REPLACE"
    )
    res_bad = await SurgicalDiffPatcher.apply_surgical_diff("tests/sandbox_scratch", "calculator.py", malformed_diff)
    assert not res_bad["success"], "Malformed diff was not rejected!"
    assert "syntax" in res_bad["error"].lower(), "Expected syntax error message"
    # Ensure disk was untouched
    assert target_file.read_text(encoding="utf-8") == original_code, "Disk was modified after failed syntax check!"
    print("  [OK] Malformed AST diff rejected; disk untouched")

    # 3. Test Valid Surgical Diff Application & Unified Diff Generation
    valid_diff = (
        "<<<< SEARCH\n"
        "def multiply(a: int, b: int) -> int:\n"
        "    return a * b\n"
        "====\n"
        "def multiply(a: int, b: int) -> int:\n"
        "    # Added docstring and operation logging\n"
        "    return a * b\n"
        ">>>> REPLACE"
    )
    res_good = await SurgicalDiffPatcher.apply_surgical_diff("tests/sandbox_scratch", "calculator.py", valid_diff)
    assert res_good["success"], f"Valid diff failed: {res_good['error']}"
    assert res_good["blocks_applied"] == 1
    assert "+    # Added docstring and operation logging" in res_good["unified_diff"]
    assert "Added docstring" in target_file.read_text(encoding="utf-8")
    print("  [OK] Valid surgical diff applied atomically with standard unified diff")

    # 4. Test Rollback to Checkpoint
    rolled_back = await SurgicalDiffPatcher.rollback_to_checkpoint("tests/sandbox_scratch", checkpoint_id)
    print(f"  [OK] Rollback executed (result: {rolled_back})")

    # 5. Test DockerSandboxManager execution and traceback compression
    sandbox = DockerSandboxManager(pool_size=2, timeout_seconds=5)
    await sandbox.initialize_pool("tests/sandbox_scratch")
    
    # Run test command
    cmd_res = await sandbox.run_command_in_sandbox("python -c \"print('Sandbox Test Passed: 42')\"", cwd="tests/sandbox_scratch")
    assert cmd_res["exit_code"] == 0, f"Sandbox command failed: {cmd_res}"
    assert "42" in cmd_res["stdout"]
    print(f"  [OK] Sandbox command executed via worker '{cmd_res['worker']}' with exit code 0")

    # Test traceback pruning
    noisy_stderr = (
        "Traceback (most recent call last):\n"
        "  File \"/usr/lib/python3.12/site-packages/pytest/_pytest/runner.py\", line 341, in from_call\n"
        "  File \"/usr/lib/python3.12/site-packages/pluggy/_hooks.py\", line 513, in __call__\n"
        "  File \"/workspace/tests/test_math.py\", line 14, in test_addition\n"
        "    assert add(1, 2) == 4\n"
        "E   AssertionError: assert 3 == 4\n"
    )
    compressed = DockerSandboxManager.compress_traceback(noisy_stderr)
    assert "site-packages" not in compressed
    assert "pluggy" not in compressed
    assert "AssertionError: assert 3 == 4" in compressed
    print("  [OK] Traceback compressor pruned internal framework frames while preserving failing assertion")

    # Cleanup scratch test files
    if test_dir.exists():
        shutil.rmtree(test_dir, ignore_errors=True)

    print("\n[SUCCESS] ALL BATCH 3 VERIFICATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(run_batch3_verification())
