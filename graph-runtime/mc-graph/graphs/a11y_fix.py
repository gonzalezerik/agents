"""a11y_fix graph: validate accessibility report, generate patch, deploy with approval."""

GRAPH = {
    "id": "a11y_fix",
    "display_name": "A11y Fix",
    "description": "Validate a WCAG complaint, generate a minimal code patch, and deploy with approval.",
    "entry": "audit",
    "state_schema": {
        "report_id":      {"type": "str"},
        "report":         {"type": "dict", "optional": True},
        "audit_result":   {"type": "dict", "optional": True},
        "classification": {"type": "str", "optional": True},
        "source_code":    {"type": "dict", "optional": True},
        "patch":          {"type": "dict", "optional": True},
        "commit_result":  {"type": "dict", "optional": True},
        "build_result":   {"type": "dict", "optional": True},
        "rollout_result": {"type": "dict", "optional": True},
        "verdict":        {"type": "str", "optional": True},
        "notify_result":  {"type": "dict", "optional": True},
    },
    "nodes": {
        "audit": {
            "type": "llm",
            "display": "Audit Report",
            "output_key": "audit_result",
            "system_prompt": (
                "You are an accessibility expert. Given an a11y report from a portfolio widget, "
                "determine whether it describes a real WCAG 2.1 AA violation. "
                "Respond with a JSON object: "
                '{"classification": "valid|dismissed", '
                '"wcag_criterion": "e.g. 1.4.3 Contrast", '
                '"affected_element": "CSS selector or description", '
                '"severity": "critical|major|minor", '
                '"reasoning": "concise explanation"}'
            ),
        },
        "route_audit": {
            "type": "router",
            "display": "Route Audit",
            "branches": ["valid", "dismissed"],
            "field": "classification",
        },
        "fetch_source": {
            "type": "tool",
            "display": "Fetch Source",
            "tool": "forgejo_fetch_source",
            "output_key": "source_code",
        },
        "patch": {
            "type": "llm",
            "display": "Generate Patch",
            "output_key": "patch",
            "system_prompt": (
                "You are an expert frontend developer fixing WCAG violations. "
                "Given the audit result and fetched source code, generate a minimal unified diff. "
                "Respond with a JSON object: "
                '{"file": "relative/path/to/file.tsx", '
                '"diff": "unified diff string", '
                '"explanation": "what changed and why, one sentence"}'
            ),
        },
        "approve_deploy": {
            "type": "human",
            "display": "Approve Deploy",
            "action_type": "deploy_a11y_fix",
            "gates": ["commit", "build", "rollout"],
        },
        "commit": {
            "type": "tool",
            "display": "Commit Patch",
            "tool": "forgejo_commit_patch",
            "write": True,
            "output_key": "commit_result",
        },
        "build": {
            "type": "tool",
            "display": "Trigger Build",
            "tool": "forgejo_trigger_build",
            "write": True,
            "output_key": "build_result",
        },
        "rollout": {
            "type": "tool",
            "display": "Rollout",
            "tool": "k8s_rollout_deployment",
            "write": True,
            "output_key": "rollout_result",
        },
        "verify_live": {
            "type": "evaluator",
            "display": "Verify Live",
            "contract": {"must": ["deployment_ready"], "must_not": ["crash_loop"]},
            "output_key": "verdict",
        },
        "notify": {
            "type": "tool",
            "display": "Notify Reporter",
            "tool": "notify_reporter",
            "write": True,
            "output_key": "notify_result",
        },
    },
    "edges": [
        {"from": "audit",         "to": "route_audit"},
        {"from": "route_audit",   "to": "fetch_source",   "branch": "valid"},
        {"from": "route_audit",   "to": "END",            "branch": "dismissed"},
        {"from": "fetch_source",  "to": "patch"},
        {"from": "patch",         "to": "approve_deploy"},
        {"from": "approve_deploy","to": "commit"},
        {"from": "commit",        "to": "build"},
        {"from": "build",         "to": "rollout"},
        {"from": "rollout",       "to": "verify_live"},
        {"from": "verify_live",   "to": "notify",     "branch": "pass"},
        {"from": "verify_live",   "to": "patch",      "branch": "fail"},
    ],
}


def get_graph() -> dict:
    return GRAPH
