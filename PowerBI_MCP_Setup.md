# Power BI MCP Server Setup

This project contains a custom MCP server that connects Claude/Cursor to your Power BI workspace.

## Quick Start

### 1. Refresh Token (if needed)
```bash
python3 -c "
import msal, os
CLIENT_ID = '13d1a7d0-98f3-4e1f-9927-ee7a1e54f0b9'
TENANT_ID = '1d4fc9ba-b027-4a5d-92d1-61baaa23c498'
SCOPES = ['https://analysis.windows.net/powerbi/api/.default']
CACHE_FILE = os.path.expanduser('~/.powerbi_mcp_token_cache.json')
cache = msal.SerializableTokenCache()
app = msal.PublicClientApplication(CLIENT_ID, authority=f'https://login.microsoftonline.com/{TENANT_ID}', token_cache=cache)
result = app.acquire_token_interactive(SCOPES)
if 'access_token' in result:
    with open(CACHE_FILE, 'w') as f: f.write(cache.serialize())
    print('Success! Token cached.')
else:
    print(f'Error: {result.get(\"error_description\")}')
"
```

### 2. Restart Cursor
Quit (`Cmd + Q`) and reopen Cursor.

### 3. Verify Connection
Check **Cursor Settings > Features > MCP** - the `powerbi` server should show a green dot.

---

## What You Can Ask Claude

Once connected, you can ask:
- "List my Power BI datasets"
- "How many reports do I have?"
- "Show me the schema for EdTA Revenue"

---

## Files

| File | Purpose |
|------|---------|
| `powerbi_client.py` | MCP server script (Python) |
| `mcp.json` | Project MCP configuration |
| `STATUS.md` | Current connection status |
| `CHAT_SUMMARY.md` | Setup session summary |

---

## Troubleshooting

### Red dot in MCP settings?
1. Run the token refresh command above
2. Restart Cursor

### 401 Unauthorized errors?
Your token may have expired. Run the refresh command.

### Missing permissions?
Go to [Azure Portal > App Registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade) and add the needed permissions under **API Permissions**.

---

## Azure App Details

- **App Name**: Power BI REST API - Claude
- **Client ID**: `13d1a7d0-98f3-4e1f-9927-ee7a1e54f0b9`
- **Tenant ID**: `1d4fc9ba-b027-4a5d-92d1-61baaa23c498`
- **Account**: wpho@schooltheatre.org

### Configured Permissions
- Dataset.Read.All, Dataset.ReadWrite.All
- Workspace.Read.All
- Report.Read.All, Report.ReadWrite.All, Report.Execute.All, Report.Reshare.All
