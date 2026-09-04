import os

TOKEN      = os.environ.get("MC_AGENT_TOKEN", "")
PORT       = int(os.environ.get("MC_AGENT_PORT", "4001"))
DB_PATH    = os.environ.get("MC_STATE_DB", "/var/lib/mission-control/state.db")
HOST_ID    = os.environ.get("MC_HOST_ID", "gpuhost")
