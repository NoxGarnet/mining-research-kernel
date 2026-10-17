"""Synthetic bounded JSON-RPC stdio server for Zotero Host tests."""
from __future__ import annotations

import json
import sys
import time

MODE = sys.argv[1] if len(sys.argv) > 1 else "normal"
OPERATIONS = ["zotero_get_collections", "zotero_get_collection_items",
              "zotero_get_item_metadata", "zotero_get_item_children",
              "zotero_get_item_fulltext", "zotero_search_items", "zotero_read_pdf_pages"]

if MODE == "no_read":
    while True:
        time.sleep(0.05)


def send(value):
    sys.stdout.write(json.dumps(value) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    if MODE == "timeout":
        time.sleep(10)
        continue
    if MODE == "malformed":
        sys.stdout.write("{bad json}\n")
        sys.stdout.flush()
        continue
    try:
        request = json.loads(line)
    except Exception:
        continue
    method = request.get("method")
    if "id" not in request:
        continue
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {},
                  "serverInfo": {"name": "synthetic", "version": "1"}}
    elif method == "tools/list":
        if MODE == "paginated":
            first = request.get("params", {}).get("cursor") is None
            names = OPERATIONS[:3] if first else OPERATIONS[3:]
            result = {"tools": [{"name": name, "inputSchema": {"type": "object"}}
                                for name in names]}
            if first:
                result["nextCursor"] = "page-2"
        else:
            names = OPERATIONS[:-1] if MODE == "missing_tools" else OPERATIONS
            result = {"tools": [{"name": name, "inputSchema": {"type": "object"}}
                                for name in names]}
    elif method == "tools/call":
        name = request.get("params", {}).get("name")
        if name == "zotero_get_collections":
            result = {"content": [{"type": "text", "text": "# Zotero Collections\n[]"}]}
        elif name == "zotero_search_items":
            result = {"content": [{"type": "text", "text": "[]"}]}
        elif name == "zotero_get_item_metadata":
            key = request.get("params", {}).get("arguments", {}).get("item_key")
            data = ({"key": key, "parentItem": "PAPER001", "itemType": "attachment",
                     "contentType": "application/pdf", "version": 2}
                    if key == "ATTACH01" else
                    {"key": key, "itemType": "journalArticle", "title": "Synthetic paper",
                     "version": 1, "collections": []})
            result = {"content": [{"type": "text", "text": json.dumps({
                "key": key, "library": {"id": 12345, "type": "user"}, "data": data
            })}]}
        elif name == "zotero_read_pdf_pages":
            result = {"content": [{"type": "text", "text": "# PDF Pages 1-1 of PDF\n**Item Key:** ATTACH01\n## Page 1\n" + ("Complete synthetic page text. " * 200)}]}
        else:
            result = {"content": [{"type": "text", "text": "[]"}]}
    else:
        result = {}
    if MODE == "rpc_error":
        if method == "tools/call":
            send({"jsonrpc": "2.0", "id": request["id"], "error": {"code": -1, "message": "fixture secret"}})
        else:
            send({"jsonrpc": "2.0", "id": request["id"], "result": result})
    else:
        send({"jsonrpc": "2.0", "id": request["id"], "result": result})
    if MODE == "stall_stdin" and method == "tools/list":
        while True:
            time.sleep(0.05)
