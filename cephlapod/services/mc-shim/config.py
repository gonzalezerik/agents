import os

TOKEN            = os.environ.get("MC_AGENT_TOKEN", "")
PORT             = int(os.environ.get("MC_SHIM_PORT", "4000"))
HOST_ID          = os.environ.get("MC_HOST_ID", "gpuhost")
EVENTS_DB        = os.environ.get("MC_EVENTS_DB", "/var/lib/mc-agent/events.db")

# mc-agent base URL (same host, loopback is fine)
MC_AGENT_URL     = os.environ.get("MC_AGENT_URL", "http://127.0.0.1:4001")
MC_AGENT_TOKEN   = TOKEN  # shared token

# Orchestrator model's llama-server port — resolved dynamically from mc-agent
# This is a fallback if mc-agent can't resolve it
FALLBACK_ORCH_PORT = int(os.environ.get("MC_ORCH_PORT", "8002"))
