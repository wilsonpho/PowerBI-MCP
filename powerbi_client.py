#!/usr/bin/env python3
"""Power BI MCP Server - Connects Claude Code to Power BI REST API"""

import warnings
warnings.filterwarnings("ignore")

import json
import sys
import os
from typing import Optional, List, Dict, Any

import msal
import requests

# Azure AD App Registration
CLIENT_ID = "13d1a7d0-98f3-4e1f-9927-ee7a1e54f0b9"
TENANT_ID = "1d4fc9ba-b027-4a5d-92d1-61baaa23c498"
AUTHORITY = "https://login.microsoftonline.com/" + TENANT_ID
SCOPES = ["https://analysis.windows.net/powerbi/api/.default"]
BASE_URL = "https://api.powerbi.com/v1.0/myorg"
CACHE_FILE = os.path.expanduser("~/.powerbi_mcp_token_cache.json")

# Workspace cache (populated lazily)
_workspace_cache = None  # type: Optional[List[Dict]]
_dataset_workspace_map = {}  # type: Dict[str, str]


class PowerBIAuthError(Exception):
    pass


# --- Auth ---

def get_access_token():
    # type: () -> str
    cache = msal.SerializableTokenCache()
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            cache.deserialize(f.read())

    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)
    accounts = app.get_accounts()
    if not accounts:
        raise PowerBIAuthError(
            "No cached accounts. Run this to authenticate:\n"
            "python3 -c \"\n"
            "import msal, os\n"
            "app = msal.PublicClientApplication("
            "'13d1a7d0-98f3-4e1f-9927-ee7a1e54f0b9', "
            "authority='https://login.microsoftonline.com/1d4fc9ba-b027-4a5d-92d1-61baaa23c498')\n"
            "result = app.acquire_token_interactive("
            "['https://analysis.windows.net/powerbi/api/.default'])\n"
            "if 'access_token' in result:\n"
            "    cache = app.token_cache\n"
            "    with open(os.path.expanduser('~/.powerbi_mcp_token_cache.json'), 'w') as f:\n"
            "        f.write(cache.serialize())\n"
            "    print('Success!')\n"
            "else: print(result.get('error_description', 'Failed'))\n"
            "\""
        )

    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if not result or "access_token" not in result:
        raise PowerBIAuthError(
            "Token expired. Run the authentication command above to refresh."
        )

    if cache.has_state_changed:
        with open(CACHE_FILE, "w") as f:
            f.write(cache.serialize())

    return result["access_token"]


# --- API Helpers ---

def _headers():
    # type: () -> Dict[str, str]
    return {"Authorization": "Bearer " + get_access_token()}


def _format_error(resp):
    # type: (requests.Response) -> str
    status = resp.status_code
    if status == 401:
        return "Authentication failed (401). Token may be expired. Re-authenticate and restart."
    if status == 403:
        return "Permission denied (403). Check Azure AD app permissions for this resource."
    if status == 404:
        return "Not found (404). Check that the ID exists and you have access."
    try:
        body = resp.json()
        msg = body.get("error", {}).get("message", resp.text)
    except Exception:
        msg = resp.text
    return "HTTP {} - {}".format(status, msg)


def api_get(path):
    # type: (str) -> Any
    resp = requests.get(BASE_URL + path, headers=_headers())
    if not resp.ok:
        raise Exception(_format_error(resp))
    return resp.json()


def api_post(path, body):
    # type: (str, Dict) -> Any
    headers = _headers()
    headers["Content-Type"] = "application/json"
    resp = requests.post(BASE_URL + path, headers=headers, json=body)
    if not resp.ok:
        raise Exception(_format_error(resp))
    if resp.status_code == 202:
        return {"status": "accepted", "message": "Refresh triggered successfully."}
    return resp.json()


# --- Workspace Resolution ---

def get_workspaces():
    # type: () -> List[Dict]
    global _workspace_cache
    if _workspace_cache is not None:
        return _workspace_cache
    data = api_get("/groups")
    _workspace_cache = data.get("value", [])
    return _workspace_cache


def _resolve_workspace_path(dataset_id, workspace_id=None):
    # type: (str, Optional[str]) -> str
    """Return the API path prefix for a dataset, resolving workspace if needed."""
    if workspace_id:
        return "/groups/" + workspace_id
    # Check cache
    if dataset_id in _dataset_workspace_map:
        return "/groups/" + _dataset_workspace_map[dataset_id]
    # Try "My Workspace" first
    resp = requests.get(
        BASE_URL + "/datasets/" + dataset_id, headers=_headers()
    )
    if resp.ok:
        _dataset_workspace_map[dataset_id] = ""
        return ""
    # Search workspaces
    for ws in get_workspaces():
        ws_id = ws["id"]
        resp = requests.get(
            BASE_URL + "/groups/" + ws_id + "/datasets/" + dataset_id,
            headers=_headers(),
        )
        if resp.ok:
            _dataset_workspace_map[dataset_id] = ws_id
            return "/groups/" + ws_id
    raise Exception(
        "Dataset '{}' not found in any accessible workspace.".format(dataset_id)
    )


# --- Tool Handlers ---

def handle_list_workspaces(args):
    # type: (Dict) -> str
    workspaces = get_workspaces()
    result = []
    for ws in workspaces:
        result.append({
            "id": ws.get("id"),
            "name": ws.get("name"),
            "type": ws.get("type"),
            "isOnDedicatedCapacity": ws.get("isOnDedicatedCapacity"),
        })
    return json.dumps(result, indent=2)


def handle_list_datasets(args):
    # type: (Dict) -> str
    workspace_id = args.get("workspace_id")
    if workspace_id:
        data = api_get("/groups/" + workspace_id + "/datasets")
    else:
        # Combine My Workspace + all group workspaces
        all_datasets = []
        try:
            my = api_get("/datasets")
            for ds in my.get("value", []):
                ds["workspaceName"] = "My Workspace"
            all_datasets.extend(my.get("value", []))
        except Exception:
            pass
        for ws in get_workspaces():
            try:
                grp = api_get("/groups/" + ws["id"] + "/datasets")
                for ds in grp.get("value", []):
                    ds["workspaceName"] = ws.get("name", "Unknown")
                    ds["workspaceId"] = ws["id"]
                all_datasets.extend(grp.get("value", []))
            except Exception:
                pass
        return json.dumps(all_datasets, indent=2)
    datasets = data.get("value", [])
    return json.dumps(datasets, indent=2)


def handle_list_reports(args):
    # type: (Dict) -> str
    workspace_id = args.get("workspace_id")
    if workspace_id:
        data = api_get("/groups/" + workspace_id + "/reports")
        return json.dumps(data.get("value", []), indent=2)

    all_reports = []
    try:
        my = api_get("/reports")
        for r in my.get("value", []):
            r["workspaceName"] = "My Workspace"
        all_reports.extend(my.get("value", []))
    except Exception:
        pass
    for ws in get_workspaces():
        try:
            grp = api_get("/groups/" + ws["id"] + "/reports")
            for r in grp.get("value", []):
                r["workspaceName"] = ws.get("name", "Unknown")
                r["workspaceId"] = ws["id"]
            all_reports.extend(grp.get("value", []))
        except Exception:
            pass
    return json.dumps(all_reports, indent=2)


def handle_get_dataset_tables(args):
    # type: (Dict) -> str
    dataset_id = args["dataset_id"]
    prefix = _resolve_workspace_path(dataset_id, args.get("workspace_id"))
    data = api_get(prefix + "/datasets/" + dataset_id + "/tables")
    return json.dumps(data.get("value", []), indent=2)


def handle_execute_dax_query(args):
    # type: (Dict) -> str
    dataset_id = args["dataset_id"]
    dax_query = args["dax_query"]
    prefix = _resolve_workspace_path(dataset_id, args.get("workspace_id"))
    body = {
        "queries": [{"query": dax_query}],
        "serializerSettings": {"includeNulls": True},
    }
    result = api_post(prefix + "/datasets/" + dataset_id + "/executeQueries", body)
    if "results" in result and result["results"]:
        tables = result["results"][0].get("tables", [])
        if tables:
            return json.dumps(tables[0].get("rows", []), indent=2)
    return json.dumps(result, indent=2)


def handle_get_datasources(args):
    # type: (Dict) -> str
    dataset_id = args["dataset_id"]
    prefix = _resolve_workspace_path(dataset_id, args.get("workspace_id"))
    data = api_get(prefix + "/datasets/" + dataset_id + "/datasources")
    return json.dumps(data.get("value", []), indent=2)


def handle_refresh_dataset(args):
    # type: (Dict) -> str
    dataset_id = args["dataset_id"]
    prefix = _resolve_workspace_path(dataset_id, args.get("workspace_id"))
    result = api_post(prefix + "/datasets/" + dataset_id + "/refreshes", {})
    return json.dumps(result, indent=2)


def handle_get_refresh_history(args):
    # type: (Dict) -> str
    dataset_id = args["dataset_id"]
    prefix = _resolve_workspace_path(dataset_id, args.get("workspace_id"))
    data = api_get(prefix + "/datasets/" + dataset_id + "/refreshes")
    return json.dumps(data.get("value", []), indent=2)


# --- Tool Registry ---

WORKSPACE_ID_PROP = {
    "type": "string",
    "description": "Optional workspace/group ID. If omitted, searches all accessible workspaces.",
}

TOOLS = [
    {
        "name": "list_workspaces",
        "description": "List all Power BI workspaces you have access to",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "handler": handle_list_workspaces,
    },
    {
        "name": "list_datasets",
        "description": "List Power BI datasets. Optionally filter by workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {"workspace_id": WORKSPACE_ID_PROP},
            "required": [],
        },
        "handler": handle_list_datasets,
    },
    {
        "name": "list_reports",
        "description": "List Power BI reports. Optionally filter by workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {"workspace_id": WORKSPACE_ID_PROP},
            "required": [],
        },
        "handler": handle_list_reports,
    },
    {
        "name": "get_dataset_tables",
        "description": "Get the tables and column schema for a Power BI dataset",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string", "description": "The dataset ID"},
                "workspace_id": WORKSPACE_ID_PROP,
            },
            "required": ["dataset_id"],
        },
        "handler": handle_get_dataset_tables,
    },
    {
        "name": "execute_dax_query",
        "description": "Execute a DAX query against a Power BI dataset. Example: EVALUATE SUMMARIZE(Sales, Sales[Category], \"Total\", SUM(Sales[Amount]))",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string", "description": "The dataset ID"},
                "dax_query": {"type": "string", "description": "The DAX query to execute"},
                "workspace_id": WORKSPACE_ID_PROP,
            },
            "required": ["dataset_id", "dax_query"],
        },
        "handler": handle_execute_dax_query,
    },
    {
        "name": "get_datasources",
        "description": "Get data source connection details and gateway info for a dataset",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string", "description": "The dataset ID"},
                "workspace_id": WORKSPACE_ID_PROP,
            },
            "required": ["dataset_id"],
        },
        "handler": handle_get_datasources,
    },
    {
        "name": "refresh_dataset",
        "description": "Trigger an async refresh for a Power BI dataset",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string", "description": "The dataset ID"},
                "workspace_id": WORKSPACE_ID_PROP,
            },
            "required": ["dataset_id"],
        },
        "handler": handle_refresh_dataset,
    },
    {
        "name": "get_refresh_history",
        "description": "Get the refresh history and status for a Power BI dataset",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string", "description": "The dataset ID"},
                "workspace_id": WORKSPACE_ID_PROP,
            },
            "required": ["dataset_id"],
        },
        "handler": handle_get_refresh_history,
    },
]

TOOL_MAP = {t["name"]: t for t in TOOLS}


# --- JSON-RPC Server ---

def send(response):
    # type: (Dict) -> None
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def tool_definitions():
    # type: () -> List[Dict]
    return [
        {"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
        for t in TOOLS
    ]


def main():
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break

            request = json.loads(line.strip())
            method = request.get("method", "")
            req_id = request.get("id")

            if method == "initialize":
                send({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "powerbi", "version": "2.0.0"},
                    },
                })

            elif method == "notifications/initialized":
                pass

            elif method == "tools/list":
                send({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": tool_definitions()},
                })

            elif method == "tools/call":
                params = request.get("params", {})
                tool_name = params.get("name", "")
                tool_args = params.get("arguments", {})

                tool = TOOL_MAP.get(tool_name)
                if not tool:
                    send({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": "Unknown tool: " + tool_name},
                    })
                    continue

                try:
                    result_text = tool["handler"](tool_args)
                    send({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {"content": [{"type": "text", "text": result_text}]},
                    })
                except PowerBIAuthError as e:
                    send({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": str(e)}],
                            "isError": True,
                        },
                    })
                except Exception as e:
                    send({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": "Error: " + str(e)}],
                            "isError": True,
                        },
                    })

            else:
                if req_id is not None:
                    send({"jsonrpc": "2.0", "id": req_id, "result": {}})

        except json.JSONDecodeError:
            continue
        except Exception as e:
            if "req_id" in dir() and req_id is not None:
                send({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32603, "message": str(e)},
                })


if __name__ == "__main__":
    main()
