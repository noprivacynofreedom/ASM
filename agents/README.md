# Atlas Agent Instrumentation SDK

The local Atlas server exposes a loopback-only observability API under `/api/ops`.

```python
from atlas_agent_runtime import AtlasAgent
agent = AtlasAgent(name='coder-01', model='coder')
agent.register()
agent.event('task.started', 'Implementing parser', trace_id='task-trace-123')
agent.task_id = 'task-123'
agent.task_stage = 'implementation'
agent.heartbeat(status='working', metrics={'cpu_percent': 24.1, 'ram_bytes': 512000000})
agent.start_heartbeats(interval=10)
# On orderly shutdown:
agent.close()
```

## API

- `POST /api/ops/agents/register` creates an agent identity and returns a per-agent bearer token.
- `POST /api/ops/agents/{id}/heartbeat` updates PID, parent PID, host, model, task, stage and metrics.
- `POST /api/ops/agents/{id}/events` ingests structured logs. Include `trace_id`, `span_id`, `parent_span_id` and `task_id` to correlate handoffs.
- `POST /api/ops/agents/{id}/frames` ingests a JPEG/PNG/WebP screenshot (2 MB maximum).
- `GET /api/ops/agents` returns the registry and latest frame metadata.
- `GET /api/ops/events?after=0` returns ordered events and a cursor.
- `GET /api/ops/events/stream?after=0` provides a 20-second Server-Sent Events stream; reconnect using the last event ID.
- `GET /api/ops/frames/{frame_id}` returns image bytes.

Screenshot capture is opt-in per SDK instance: `AtlasAgent(..., screenshot_opt_in=True).capture_screenshot()`.
Install optional capture dependencies with `py -3 -m pip install mss pillow`. Capture is a still image, not a remote-control stream. Do not enable it for unattended or sensitive desktops without explicit user consent.

The service binds only to `127.0.0.1` via the existing Atlas server. Do not expose it directly to a network. A remote deployment needs TLS, node identity integration, rate limits and access control through the Atlas Control Plane before enabling remote agents.
