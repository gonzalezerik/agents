"""Forgejo MCP server: read repos, commit patches, trigger CI."""
import os, sys
sys.path.insert(0, "/opt/mc-graph")
from mcp.server import make_mcp_app
from tools import forgejo_fetch_source, forgejo_commit_patch, forgejo_trigger_build

TOOLS = [
    {
        "name": "forgejo_fetch_source",
        "description": "Fetch source file content from Forgejo repo.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path in repo, e.g. app/globals.css"},
                "repo": {"type": "string", "description": "Repo name (default: mission-control)"},
            },
        },
        "handler": forgejo_fetch_source,
    },
    {
        "name": "forgejo_commit_patch",
        "description": "Apply a unified diff and commit to Forgejo (write, requires approval gate).",
        "inputSchema": {
            "type": "object",
            "required": ["file", "diff", "explanation"],
            "properties": {
                "file": {"type": "string"},
                "diff": {"type": "string"},
                "explanation": {"type": "string"},
                "branch": {"type": "string", "default": "main"},
            },
        },
        "handler": forgejo_commit_patch,
    },
    {
        "name": "forgejo_trigger_build",
        "description": "Trigger a Forgejo CI workflow run (write).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "default": "main"},
                "repo": {"type": "string"},
            },
        },
        "handler": forgejo_trigger_build,
    },
]

ALLOWED_GRAPHS = {"a11y_fix"}

app = make_mcp_app("mc-forgejo", "0.1.0", TOOLS)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("MCP_FORGEJO_PORT", "4011"))
    uvicorn.run(app, host="0.0.0.0", port=port)
