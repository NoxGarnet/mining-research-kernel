import json
import sys

TOOLS = [
    {"name": "itasca_browse_commands"},
    {"name": "itasca_browse_reference"},
    {"name": "itasca_query_command"},
    {"name": "itasca_execute_task"},
    {"name": "itasca_execute_code"},
]

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "notifications/initialized":
        continue
    if "id" not in request:
        continue
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {},
                  "serverInfo": {"name": "itasca-test", "version": "0.7.0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        args = request["params"]["arguments"]
        result = {"structuredContent": {
            "ok": True,
            "data": {
                "source": "commands", "action": "browse",
                "entries": [{"category": "model", "command": "model save",
                             "version": args["version"],
                             "doc": {"source": "https://docs.example.invalid/model-save",
                                     "description": "Saves the current model.",
                                     "syntax": "model save file-name"}}],
                "summary": {"count": 1, "version": args["version"],
                            "software": args["software"]},
            },
        }}
    else:
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
