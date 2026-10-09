"""Base MCP server: exposes tools over HTTP (JSON-RPC 2.0, MCP spec §2)."""
import json, logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

log = logging.getLogger("mc-graph.mcp")


def make_mcp_app(server_name: str, server_version: str, tools: list[dict]) -> FastAPI:
    """
    Build a FastAPI app that speaks the Model Context Protocol over HTTP.
    tools: list of {"name": str, "description": str, "inputSchema": dict, "handler": async fn}
    """
    tool_map = {t["name"]: t for t in tools}
    app = FastAPI(title=server_name)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    def _tool_def(t: dict) -> dict:
        return {"name": t["name"], "description": t["description"],
                "inputSchema": t.get("inputSchema", {"type": "object", "properties": {}})}

    @app.get("/")
    async def root():
        return {"name": server_name, "version": server_version, "protocol": "mcp/1.0"}

    @app.post("/")
    async def handle_jsonrpc(req: Request):
        body = await req.json()
        method = body.get("method", "")
        params = body.get("params", {})
        rpc_id = body.get("id")

        def ok(result):
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": result})

        def err(code, message):
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id,
                                 "error": {"code": code, "message": message}})

        if method == "initialize":
            return ok({
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": server_name, "version": server_version},
            })

        if method == "tools/list":
            return ok({"tools": [_tool_def(t) for t in tools]})

        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments", {})
            if name not in tool_map:
                return err(-32601, f"Tool not found: {name}")
            try:
                result = await tool_map[name]["handler"](**args)
                return ok({"content": [{"type": "text", "text": json.dumps(result)}]})
            except Exception as exc:
                log.error("MCP tool %s error: %s", name, exc)
                return ok({"content": [{"type": "text", "text": json.dumps({"error": str(exc)})}],
                           "isError": True})

        return err(-32601, f"Method not found: {method}")

    return app
