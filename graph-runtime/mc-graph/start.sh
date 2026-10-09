#!/bin/bash
set -a; source /etc/mc-graph/env; set +a
cd /opt/mc-graph
exec .venv/bin/uvicorn main:app --host 0.0.0.0 --port 4002
