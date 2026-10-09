"""generator_evaluator: reusable generate → evaluate → (pass|retry|fail) subgraph factory."""


def get_graph(
    graph_id: str = "generator_evaluator",
    display_name: str = "Generator + Evaluator",
    description: str = "Generate content, evaluate against contract, retry or pass.",
    generate_tool: str = "studio_generate",
    evaluate_contract: dict | None = None,
    max_retries: int = 3,
) -> dict:
    contract = evaluate_contract or {
        "must": ["output_valid", "no_errors"],
        "must_not": ["nsfw", "timeout"],
    }
    return {
        "id": graph_id,
        "display_name": display_name,
        "description": description,
        "entry": "generate",
        "state_schema": {
            "prompt":      {"type": "str"},
            "parameters":  {"type": "dict", "optional": True},
            "generated":   {"type": "dict", "optional": True},
            "retry_count": {"type": "int", "optional": True},
            "verdict":     {"type": "str", "optional": True},
        },
        "nodes": {
            "generate": {
                "type": "tool",
                "display": "Generate",
                "tool": generate_tool,
                "output_key": "generated",
            },
            "evaluate": {
                "type": "evaluator",
                "display": "Evaluate",
                "contract": contract,
                "output_key": "verdict",
            },
            "check_retry": {
                "type": "router",
                "display": "Retry?",
                "branches": ["pass", "retry", "fail"],
                "field": "verdict",
            },
        },
        "edges": [
            {"from": "generate",    "to": "evaluate"},
            {"from": "evaluate",    "to": "check_retry"},
            {"from": "check_retry", "to": "END",      "branch": "pass"},
            {"from": "check_retry", "to": "generate", "branch": "retry"},
            {"from": "check_retry", "to": "END",      "branch": "fail"},
        ],
    }
