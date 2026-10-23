from typing import List, Dict, Any

class ContextCompactor:
    """
    Context Compactor for managing agent token limits (30k token ceiling).
    Automatically trims intermediate tool outputs and prior retry tracebacks
    while preserving the core system prompt, AST repo map, and latest sandbox results.
    """

    MAX_CONTEXT_TOKENS: int = 30000

    @classmethod
    def estimate_tokens(cls, text: str) -> int:
        return len(text) // 4

    @classmethod
    def compact_history(
        cls,
        messages: List[Dict[str, str]],
        max_tokens: int = MAX_CONTEXT_TOKENS
    ) -> List[Dict[str, str]]:
        total_tokens = sum(cls.estimate_tokens(m.get("content", "")) for m in messages)
        if total_tokens <= max_tokens:
            return messages

        compacted = []
        # Always retain system message
        if messages and messages[0].get("role") == "system":
            compacted.append(messages[0])
            candidates = messages[1:]
        else:
            candidates = messages

        # Retain last 4 messages intact
        recent = candidates[-4:] if len(candidates) >= 4 else candidates
        older = candidates[:-4] if len(candidates) >= 4 else []

        # Summarize older messages
        if older:
            summary_content = (
                f"[Context Compactor: Pruned {len(older)} intermediate locator/diff steps "
                f"to maintain sub-30k token context window.]"
            )
            compacted.append({"role": "system", "content": summary_content})

        compacted.extend(recent)
        return compacted
