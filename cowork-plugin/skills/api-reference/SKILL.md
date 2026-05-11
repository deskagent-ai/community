# DeskAgent REST API Reference

DeskAgent exposes a FastAPI-based REST API for external tools and integrations.

## Overview

| Property | Value |
|----------|-------|
| **Base URL** | `http://localhost:8765` |
| **Authentication** | None (localhost only) |
| **Full API Docs** | http://localhost:8765/docs |
| **External API Docs** | http://localhost:8765/api/external/docs |

The API uses JSON for request/response bodies and Server-Sent Events (SSE) for real-time streaming.

### Two Swagger Interfaces

| URL | Purpose | Endpoints |
|-----|---------|-----------|
| `/docs` | Full internal API | All 170+ endpoints |
| `/api/external/docs` | External tools | ~15 safe endpoints |

For external integrations, use `/api/external/` endpoints - they have optional API key auth and limited scope.

---

## Agent Execution

### Start Agent (GET)

Start an agent without inputs.

```
GET /agent/{agent_name}
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `backend` | string | - | Override AI backend (e.g., "gemini") |
| `dry_run` | bool | false | Simulate destructive operations |
| `test_folder` | string | - | Outlook folder for test scenarios |
| `triggered_by` | string | "webui" | Source: webui, voice, api, workflow |

**Response:**
```json
{
  "task_id": "abc123",
  "status": "running",
  "agent": "daily_check",
  "stream_url": "/task/abc123/stream"
}
```

### Start Agent (POST)

Start an agent with inputs.

```
POST /agent/{agent_name}
```

**Request Body:**
```json
{
  "inputs": {
    "customer_name": "ACME GmbH",
    "email_address": "info@acme.de"
  },
  "backend": "gemini",
  "dry_run": false,
  "triggered_by": "api"
}
```

**Response:** Same as GET.

### Submit Prompt

Submit a free-form prompt.

```
POST /prompt
```

**Request Body:**
```json
{
  "prompt": "What is the status of my last invoice?",
  "continue_context": true,
  "backend": "claude",
  "triggered_by": "api"
}
```

---

## Task Streaming (SSE)

### Stream Task Events

Real-time task updates via Server-Sent Events.

```
GET /task/{task_id}/stream
```

**SSE Events:**

| Event | Description | Data |
|-------|-------------|------|
| `task_start` | Task started | `{task_id, model, agent, backend, status}` |
| `token` | Streaming token | `{token, is_thinking, accumulated_length}` |
| `tool_call` | Tool execution | `{tool_name, status, result}` |
| `pending_input` | Dialog needed | `{type, title, fields}` |
| `task_complete` | Task finished | `{status, result, input_tokens, output_tokens, cost_usd, duration}` |
| `task_error` | Task failed | `{error}` |
| `task_cancelled` | Task cancelled | `{}` |
| `ping` | Keepalive (15s) | `{}` |

**Example (curl):**
```bash
curl -N "http://localhost:8765/task/abc123/stream"
```

**Example (Python):**
```python
import requests

with requests.get("http://localhost:8765/task/abc123/stream", stream=True) as r:
    for line in r.iter_lines():
        if line:
            print(line.decode())
```

### Get Task Status

Polling fallback for task status.

```
GET /task/{task_id}/status
```

**Response:**
```json
{
  "task_id": "abc123",
  "status": "running",
  "agent": "daily_check",
  "streaming": {
    "content": "Processing emails...",
    "length": 42
  }
}
```

### Cancel Task

Cancel a running task.

```
POST /task/{task_id}/cancel
```

**Response:**
```json
{"status": "ok", "cancelled": true}
```

### Respond to Dialog

Submit response to pending confirmation dialog.

```
POST /task/{task_id}/respond
```

**Request Body:**
```json
{
  "confirmed": true,
  "data": {"selected_option": "A"}
}
```

---

## Discovery

### List Agents

```
GET /agents
```

**Response:**
```json
{
  "agents": ["daily_check", "reply_email", "create_offer"]
}
```

### List Skills

```
GET /skills
```

**Response:**
```json
{
  "skills": ["push", "release", "test"]
}
```

### List Backends

```
GET /backends
```

**Response:**
```json
{
  "enabled": ["claude", "gemini", "gemini_flash"],
  "default": "claude",
  "count": 3,
  "details": {
    "claude": {"type": "claude_agent_sdk", "model": "claude-sonnet-4-20250514"}
  }
}
```

### Get Agent Inputs

Get input field definitions for an agent.

```
GET /agent/{agent_name}/inputs
```

**Response:**
```json
{
  "inputs": [
    {"name": "customer_name", "type": "text", "label": "Kundenname", "required": true},
    {"name": "amount", "type": "number", "label": "Betrag"}
  ]
}
```

### Check Agent Prerequisites

Check if agent's MCPs and backend are configured.

```
GET /agent/{agent_name}/prerequisites
```

**Response:**
```json
{
  "ready": true,
  "missing_mcps": [],
  "missing_backend": null,
  "hints": {}
}
```

---

## Session & History

### Get Current Session

```
GET /session
```

**Response:**
```json
{
  "session_id": "sess_abc123",
  "agent_name": "chat",
  "backend": "claude",
  "history_count": 5
}
```

### List Sessions

```
GET /history/sessions?limit=20&offset=0&agent=chat&status=completed
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 20 | Max sessions to return |
| `offset` | int | 0 | Pagination offset |
| `agent` | string | - | Filter by agent name |
| `status` | string | - | Filter: "active" or "completed" |

**Response:**
```json
{
  "sessions": [
    {
      "session_id": "sess_abc123",
      "agent_name": "chat",
      "backend": "claude",
      "started_at": "2025-01-15T10:30:00",
      "status": "completed",
      "turn_count": 5,
      "total_cost_usd": 0.0234
    }
  ],
  "total": 42,
  "total_turns": 150,
  "total_cost_usd": 1.23
}
```

### Get Session Details

```
GET /history/sessions/{session_id}
```

**Response:** Full session object including all turns.

### Continue Session

```
POST /history/sessions/{session_id}/continue
```

**Response:**
```json
{
  "agent_name": "chat",
  "backend": "claude",
  "context": "Previous conversation context...",
  "original_session_id": "sess_abc123"
}
```

### Get History Statistics

```
GET /history/stats
```

**Response:**
```json
{
  "total_sessions": 42,
  "active_sessions": 1,
  "total_turns": 150,
  "total_tokens": 50000,
  "total_cost_usd": 1.23
}
```

---

## System

### Health Check

```
GET /status
```

**Response:**
```json
{"status": "ok", "ready": true}
```

### Get Version

```
GET /version
```

**Response:**
```json
{
  "version": "1.0.6",
  "build": 42,
  "release_date": "2025-01-15"
}
```

### Get System Info

```
GET /system/info
```

**Response:**
```json
{
  "version": "1.0.6",
  "python": "3.12.0",
  "platform": "Windows 10",
  "uptime": "2h 30m",
  "paths": {
    "workspace": "C:/Users/user/DeskAgent/workspace",
    "config": "C:/Users/user/DeskAgent/config"
  }
}
```

### MCP Status

```
GET /mcp/status
```

**Response:**
```json
{
  "mcps": [
    {"name": "outlook", "installed": true, "configured": true},
    {"name": "billomat", "installed": true, "configured": false}
  ]
}
```

---

## Cost Tracking

### Get Cost Summary

```
GET /costs
```

**Response:**
```json
{
  "today_usd": 0.45,
  "month_usd": 12.34,
  "billable_total_usd": 10.50,
  "anthropic_available": true,
  "anthropic_total_usd": 12.00,
  "source": "anthropic"
}
```

### Get Detailed Costs

```
GET /costs/full
```

**Response:** Detailed breakdown by backend and day.

### Reset Costs

```
POST /costs/reset
```

---

## Examples

### Start Agent and Stream Results (Python)

```python
import requests
import json

# Start agent
response = requests.post(
    "http://localhost:8765/agent/daily_check",
    json={"triggered_by": "api"}
)
task_id = response.json()["task_id"]
print(f"Task started: {task_id}")

# Stream results
with requests.get(
    f"http://localhost:8765/task/{task_id}/stream",
    stream=True
) as r:
    for line in r.iter_lines():
        if line:
            line = line.decode()
            if line.startswith("data:"):
                data = json.loads(line[5:])
                print(data)
```

### Start Agent and Stream Results (curl)

```bash
# Start agent
TASK_ID=$(curl -s -X POST "http://localhost:8765/agent/daily_check" \
  -H "Content-Type: application/json" \
  -d '{"triggered_by": "api"}' | jq -r '.task_id')

echo "Task started: $TASK_ID"

# Stream results
curl -N "http://localhost:8765/task/$TASK_ID/stream"
```

### List and Run Agent with Inputs

```python
import requests

# Get agent inputs
inputs_resp = requests.get("http://localhost:8765/agent/create_offer/inputs")
inputs = inputs_resp.json()["inputs"]
print(f"Required inputs: {[i['name'] for i in inputs]}")

# Run agent with inputs
response = requests.post(
    "http://localhost:8765/agent/create_offer",
    json={
        "inputs": {
            "customer_name": "ACME GmbH",
            "contact_email": "info@acme.de"
        },
        "triggered_by": "api"
    }
)
task_id = response.json()["task_id"]
print(f"Task: {task_id}")
```

---

## Error Handling

All endpoints return standard HTTP status codes:

| Code | Description |
|------|-------------|
| 200 | Success |
| 400 | Bad request (invalid parameters) |
| 404 | Not found (task, agent, session) |
| 500 | Internal server error |

Error response format:
```json
{
  "detail": "Task not found"
}
```

---

## Authentication & External Access

### Current State (Localhost)

The API currently has **no authentication** - it's designed for localhost-only access:
- Binds to `127.0.0.1:8765` by default
- No API key or token required
- All endpoints are accessible without credentials

This is secure for local use since only processes on the same machine can access the API.

### Options for External Access

If you need to expose the API externally, consider these options:

#### Option 1: Reverse Proxy with Authentication (Recommended)

Use nginx or Caddy as a reverse proxy with Basic Auth or OAuth:

```nginx
# nginx example
location /api/ {
    auth_basic "DeskAgent API";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass http://127.0.0.1:8765/;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;  # Important for SSE
}
```

#### Option 2: Built-in API Key + Disable Internal Docs

DeskAgent has built-in support for API key authentication and disabling the full internal API:

```json
// system.json
{
  "api": {
    "api_key": "your-secret-key-here",
    "internal_docs_enabled": false
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `api_key` | null | API key for `/api/external/` write endpoints |
| `internal_docs_enabled` | true | Set to `false` to disable `/docs`, `/redoc`, `/openapi.json` |

With this config:
- `/docs` returns 404 (disabled)
- `/api/external/docs` works (limited endpoints)
- Write endpoints require `X-API-Key` header

Request with API key:
```bash
curl -H "X-API-Key: your-secret-key" http://localhost:8765/api/external/agent/daily_check -X POST
```

#### Option 3: Tailscale/VPN

Expose the API over a private network using Tailscale or WireGuard - no auth changes needed since traffic is already authenticated at the network level.

### Security Considerations

| Risk | Mitigation |
|------|------------|
| Unauthorized access | Use reverse proxy with auth or API keys |
| Data exposure | Only expose read-only endpoints externally |
| Agent execution | Require additional confirmation for `/agent` POST |
| CORS | Configure `allowed_origins` for browser access |

### Recommended External Endpoints

For external tools, expose only these safe endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/status` | GET | Health check |
| `/agents` | GET | List available agents |
| `/skills` | GET | List available skills |
| `/backends` | GET | List AI backends |
| `/costs` | GET | Cost tracking |
| `/history/sessions` | GET | Session history |

**Consider restricting:**
- `POST /agent/*` - Requires confirmation workflow
- `POST /shutdown` - Admin only
- `POST /restart` - Admin only

---

## Notes

- The API is designed for **localhost access only** by default
- For external access, use a reverse proxy with authentication
- SSE connections have a 15-second keepalive ping
- Task results are kept in memory until the server restarts
- Session history is persisted to SQLite database
