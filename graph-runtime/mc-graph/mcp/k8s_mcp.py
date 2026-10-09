"""K8s MCP server: read/act capabilities for Kubernetes."""
import os, sys
sys.path.insert(0, "/opt/mc-graph")
from mcp.server import make_mcp_app
from tools import k8s_gather_context, k8s_restart_pod, k8s_check_pod_health, k8s_rollout_deployment

TOOLS = [
    {
        "name": "k8s_gather_context",
        "description": "Gather K8s context: failing pods, events, recent logs for a namespace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pod_name": {"type": "string", "description": "Target pod name (optional)"},
                "namespace": {"type": "string", "default": "mission-control"},
            },
        },
        "handler": k8s_gather_context,
    },
    {
        "name": "k8s_restart_pod",
        "description": "Delete a pod to trigger restart (write, requires approval gate).",
        "inputSchema": {
            "type": "object",
            "required": ["pod_name"],
            "properties": {
                "pod_name": {"type": "string"},
                "namespace": {"type": "string", "default": "mission-control"},
            },
        },
        "handler": k8s_restart_pod,
    },
    {
        "name": "k8s_check_pod_health",
        "description": "Check if a pod is running and healthy.",
        "inputSchema": {
            "type": "object",
            "required": ["pod_name"],
            "properties": {
                "pod_name": {"type": "string"},
                "namespace": {"type": "string", "default": "mission-control"},
            },
        },
        "handler": k8s_check_pod_health,
    },
    {
        "name": "k8s_rollout_deployment",
        "description": "Annotate a K8s deployment to trigger a rolling restart.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "deployment": {"type": "string", "default": "mission-control-app"},
                "namespace": {"type": "string", "default": "mission-control"},
            },
        },
        "handler": k8s_rollout_deployment,
    },
]

# Allowed graphs: declare which graph IDs may use this server
ALLOWED_GRAPHS = {"incident_investigation", "a11y_fix"}

app = make_mcp_app("mc-k8s", "0.1.0", TOOLS)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("MCP_K8S_PORT", "4010"))
    uvicorn.run(app, host="0.0.0.0", port=port)
