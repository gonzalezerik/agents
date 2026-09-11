"""incident_investigation graph definition."""

GRAPH = {
    "id": "incident_investigation",
    "display_name": "Incident Investigation",
    "description": "Investigate an unhealthy pod, propose a fix, and restart with approval.",
    "entry": "gather_context",
    "state_schema": {
        "alert": {"type": "dict"},
        "context": {"type": "dict", "optional": True},
        "analysis": {"type": "str", "optional": True},
        "proposal": {"type": "dict", "optional": True},
        "restart_result": {"type": "dict", "optional": True},
        "verdict": {"type": "str", "optional": True},
    },
    "nodes": {
        "gather_context": {
            "type": "tool",
            "display": "Gather K8s Context",
            "tool": "k8s_gather_context",
            "output_key": "context",
        },
        "investigate": {
            "type": "llm",
            "display": "Investigate",
            "output_key": "analysis",
            "system_prompt": (
                "You are an SRE incident investigator. Given K8s context for a failing pod, "
                "analyze the root cause and propose a remediation. "
                'Respond with a JSON object: {"classification": "proposed_fix|escalate|note", '
                '"root_cause": "...", '
                '"proposal": {"type": "restart_pod", "pod": "...", "namespace": "...", '
                '"confidence": 0.0, "reasoning": "..."} or null}'
            ),
        },
        "classify": {
            "type": "router",
            "display": "Classify",
            "branches": ["proposed_fix", "escalate", "note"],
            "field": "classification",
        },
        "approve_restart": {
            "type": "human",
            "display": "Approve Restart",
            "action_type": "restart_pod",
            "gates": ["restart_pod"],
        },
        "restart_pod": {
            "type": "tool",
            "display": "Restart Pod",
            "tool": "k8s_restart_pod",
            "write": True,
            "output_key": "restart_result",
        },
        "verify": {
            "type": "evaluator",
            "display": "Verify Recovery",
            "contract": {"must": ["pod_running"], "must_not": ["crash_loop"]},
            "output_key": "verdict",
        },
    },
    "edges": [
        {"from": "gather_context", "to": "investigate"},
        {"from": "investigate", "to": "classify"},
        {"from": "classify", "to": "approve_restart", "branch": "proposed_fix"},
        {"from": "classify", "to": "END", "branch": "escalate"},
        {"from": "classify", "to": "END", "branch": "note"},
        {"from": "approve_restart", "to": "restart_pod"},
        {"from": "restart_pod", "to": "verify"},
        {"from": "verify", "to": "END", "branch": "pass"},
        {"from": "verify", "to": "investigate", "branch": "fail"},
    ],
}

def get_graph() -> dict:
    return GRAPH
