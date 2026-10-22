from typing import Literal, Dict, Any

class DualModelRouter:
    """
    Routes agent tasks between:
    - Tier 1: Architect / Planner (Frontier reasoning: scoping, architecture, multi-file bugs)
    - Tier 2: Fast-Apply / Mechanical Executor (High-speed: edits, tests, linting at 150-300+ tps)
    """
    def __init__(
        self,
        planner_model: str = "claude-3-7-sonnet",
        executor_model: str = "gemini-2.0-flash"
    ):
        self.planner_model = planner_model
        self.executor_model = executor_model

    def select_model(self, task_type: Literal["PLANNING", "SURGICAL_EDIT", "LINT_FIX", "TEST_GEN", "SYNTAX_CHECK"]) -> Dict[str, str]:
        if task_type == "PLANNING":
            return {
                "tier": "Tier-1 (Architect/Planner)",
                "model": self.planner_model,
                "temperature": "0.1",
                "max_tokens": "4096"
            }
        else:
            return {
                "tier": "Tier-2 (Fast-Apply Executor)",
                "model": self.executor_model,
                "temperature": "0.0",
                "max_tokens": "8192"
            }
