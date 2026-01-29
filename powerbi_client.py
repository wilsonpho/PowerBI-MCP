#!/usr/bin/env python3
"""Power BI MCP Server - Connects Cursor to Power BI REST API"""

import warnings
warnings.filterwarnings("ignore")

import json
import sys
import os
import msal
import requests

# Azure AD App Registration details
CLIENT_ID = "13d1a7d0-98f3-4e1f-9927-ee7a1e54f0b9"
TENANT_ID = "1d4fc9ba-b027-4a5d-92d1-61baaa23c498"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://analysis.windows.net/powerbi/api/.default"]
BASE_URL = "https://api.powerbi.com/v1.0/myorg"

# Persistent token cache file
CACHE_FILE = os.path.expanduser("~/.powerbi_mcp_token_cache.json")

def get_token_cache():
    """Load or create a persistent token cache."""
    cache = msal.SerializableTokenCache()
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            cache.deserialize(f.read())
    return cache

def save_token_cache(cache):
    """Save the token cache to disk."""
    if cache.has_state_changed:
        with open(CACHE_FILE, 'w') as f:
            f.write(cache.serialize())

def get_access_token():
    cache = get_token_cache()
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and 'access_token' in result:
            save_token_cache(cache)
            return result['access_token']
    # Fallback to interactive (won't work in MCP context, but needed for refresh script)
    result = app.acquire_token_interactive(SCOPES)
    save_token_cache(cache)
    return result.get('access_token')

def list_datasets():
    token = get_access_token()
    if not token:
        return [{"error": "Failed to get access token"}]
    headers = {'Authorization': f'Bearer {token}'}
    response = requests.get(f"{BASE_URL}/datasets", headers=headers)
    response.raise_for_status()
    return response.json().get('value', [])

def list_reports():
    token = get_access_token()
    if not token:
        return [{"error": "Failed to get access token"}]
    headers = {'Authorization': f'Bearer {token}'}
    
    all_reports = []
    
    # Try "My Workspace" reports first
    try:
        my_resp = requests.get(f"{BASE_URL}/reports", headers=headers)
        if my_resp.status_code == 200:
            reports = my_resp.json().get('value', [])
            for report in reports:
                report['workspaceName'] = 'My Workspace'
            all_reports.extend(reports)
    except:
        pass
    
    # Get all workspaces/groups the user has access to
    try:
        groups_resp = requests.get(f"{BASE_URL}/groups", headers=headers)
        groups_resp.raise_for_status()
        groups = groups_resp.json().get('value', [])
    except:
        groups = []
    
    # Also check the known workspace from datasets (fallback)
    known_workspace_id = "3e1e5768-79cc-40af-9b57-c67d6781be9c"
    if not any(g['id'] == known_workspace_id for g in groups):
        groups.append({'id': known_workspace_id, 'name': 'EdTA Workspace'})
    
    for group in groups:
        group_id = group['id']
        group_name = group.get('name', 'Unknown')
        try:
            reports_resp = requests.get(f"{BASE_URL}/groups/{group_id}/reports", headers=headers)
            if reports_resp.status_code == 200:
                reports = reports_resp.json().get('value', [])
                for report in reports:
                    report['workspaceName'] = group_name
                    report['workspaceId'] = group_id
                all_reports.extend(reports)
        except:
            pass
    
    return all_reports

def get_dataset_tables(dataset_id):
    """Get tables and columns for a dataset."""
    token = get_access_token()
    if not token:
        return {"error": "Failed to get access token"}
    headers = {'Authorization': f'Bearer {token}'}
    
    # Try direct endpoint first
    response = requests.get(f"{BASE_URL}/datasets/{dataset_id}/tables", headers=headers)
    if response.status_code == 200:
        return response.json().get('value', [])
    
    # Try via group
    group_id = "3e1e5768-79cc-40af-9b57-c67d6781be9c"
    response = requests.get(f"{BASE_URL}/groups/{group_id}/datasets/{dataset_id}/tables", headers=headers)
    response.raise_for_status()
    return response.json().get('value', [])

def execute_dax_query(dataset_id, dax_query):
    """Execute a DAX query against a dataset."""
    token = get_access_token()
    if not token:
        return {"error": "Failed to get access token"}
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    body = {
        "queries": [{"query": dax_query}],
        "serializerSettings": {"includeNulls": True}
    }
    
    # Try direct endpoint first
    response = requests.post(
        f"{BASE_URL}/datasets/{dataset_id}/executeQueries",
        headers=headers,
        json=body
    )
    
    if response.status_code == 404:
        # Try via group
        group_id = "3e1e5768-79cc-40af-9b57-c67d6781be9c"
        response = requests.post(
            f"{BASE_URL}/groups/{group_id}/datasets/{dataset_id}/executeQueries",
            headers=headers,
            json=body
        )
    
    response.raise_for_status()
    result = response.json()
    
    # Parse the results into a cleaner format
    if 'results' in result and result['results']:
        tables = result['results'][0].get('tables', [])
        if tables:
            return tables[0].get('rows', [])
    return result

def send_response(response):
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()

def main():
    # MCP JSON-RPC stdio server loop
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            
            request = json.loads(line.strip())
            method = request.get("method", "")
            req_id = request.get("id")
            
            # Handle MCP protocol methods
            if method == "initialize":
                send_response({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "powerbi", "version": "1.0.0"}
                    }
                })
            elif method == "notifications/initialized":
                # No response needed for notifications
                pass
            elif method == "tools/list":
                send_response({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": [
                            {
                                "name": "list_datasets",
                                "description": "List all Power BI datasets in your workspace",
                                "inputSchema": {"type": "object", "properties": {}, "required": []}
                            },
                            {
                                "name": "list_reports",
                                "description": "List all Power BI reports in your workspace",
                                "inputSchema": {"type": "object", "properties": {}, "required": []}
                            },
                            {
                                "name": "get_dataset_tables",
                                "description": "Get the tables and schema for a Power BI dataset",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "dataset_id": {
                                            "type": "string",
                                            "description": "The dataset ID (from list_datasets)"
                                        }
                                    },
                                    "required": ["dataset_id"]
                                }
                            },
                            {
                                "name": "execute_dax_query",
                                "description": "Execute a DAX query against a Power BI dataset to retrieve data",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "dataset_id": {
                                            "type": "string",
                                            "description": "The dataset ID to query"
                                        },
                                        "dax_query": {
                                            "type": "string",
                                            "description": "The DAX query to execute, e.g. EVALUATE SUMMARIZE(Sales, Sales[Category], \"Total\", SUM(Sales[Amount]))"
                                        }
                                    },
                                    "required": ["dataset_id", "dax_query"]
                                }
                            }
                        ]
                    }
                })
            elif method == "tools/call":
                tool_name = request.get("params", {}).get("name", "")
                if tool_name == "list_datasets":
                    try:
                        datasets = list_datasets()
                        result_text = json.dumps(datasets, indent=2)
                    except Exception as e:
                        result_text = f"Error: {str(e)}"
                    send_response({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": result_text}]
                        }
                    })
                elif tool_name == "list_reports":
                    try:
                        reports = list_reports()
                        result_text = json.dumps(reports, indent=2)
                    except Exception as e:
                        result_text = f"Error: {str(e)}"
                    send_response({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": result_text}]
                        }
                    })
                elif tool_name == "get_dataset_tables":
                    try:
                        args = request.get("params", {}).get("arguments", {})
                        dataset_id = args.get("dataset_id", "")
                        tables = get_dataset_tables(dataset_id)
                        result_text = json.dumps(tables, indent=2)
                    except Exception as e:
                        result_text = f"Error: {str(e)}"
                    send_response({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": result_text}]
                        }
                    })
                elif tool_name == "execute_dax_query":
                    try:
                        args = request.get("params", {}).get("arguments", {})
                        dataset_id = args.get("dataset_id", "")
                        dax_query = args.get("dax_query", "")
                        result = execute_dax_query(dataset_id, dax_query)
                        result_text = json.dumps(result, indent=2)
                    except Exception as e:
                        result_text = f"Error: {str(e)}"
                    send_response({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": result_text}]
                        }
                    })
                else:
                    send_response({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
                    })
            else:
                # Unknown method - return empty result
                if req_id is not None:
                    send_response({"jsonrpc": "2.0", "id": req_id, "result": {}})
                    
        except json.JSONDecodeError:
            continue
        except Exception as e:
            if 'req_id' in locals() and req_id is not None:
                send_response({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32603, "message": str(e)}
                })

if __name__ == "__main__":
    main()
