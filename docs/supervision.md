# Supervisor Trees

Agent OS supervision trees provide Erlang/OTP-style parent-child ownership on
top of the existing process registry. The registry remains the authority for
startup, crash detection, transactional cleanup, and restarts.

## Relationships

Each process snapshot includes:

- `parent_pid`
- `child_pids`
- `child_count`
- `restart_count`
- `supervisor_strategy`
- `restart_policy`
- `supervision_escalated`

The `ps` command and dashboard show parent PID, child count, restart count, and
the active supervisor strategy.

## Strategies

Supervisors support:

- `one_for_one`: restart only the failed child.
- `one_for_all`: restart every child when one child fails.
- `rest_for_one`: restart the failed child and children started after it.

Agent classes configure their strategy with:

```python
from agentos import AgentProcess


class Coordinator(AgentProcess):
    supervisor_strategy = "one_for_one"
    max_restarts = 3
    restart_window_seconds = 60.0
    restart_backoff_seconds = 0.1
```

## Restart Policies

Children are spawned with a restart policy:

- `permanent`: always restart.
- `transient`: restart only after abnormal failure.
- `temporary`: never restart.

```python
pid = await self.spawn_child("examples/restarting_worker.py", restart_policy="permanent")
```

## SDK API

Supervisors can use:

```python
pid = await self.spawn_child("examples/worker.py")
self.monitor_child(pid)
children = self.list_children()
await self.terminate_child(pid)
```

`spawn_child` is available to trusted in-process agents attached to the registry.
The registry can supervise both trusted and isolated children because it owns
the lifecycle monitor in both modes.

## Structured Events

Supervision notifications are delivered as structured IPC `event` messages:

- `process_started`
- `process_stopped`
- `process_crashed`
- `child_restarted`
- `supervision_escalation`

Restart storms are bounded by `max_restarts` within `restart_window_seconds`.
When the threshold is exceeded, the supervisor receives a
`supervision_escalation` event and no further restart is attempted for that
failure.

## Demo

```powershell
python main.py
```

In the dashboard shell:

```text
run examples/supervisor_agent.py
ps
```

`SupervisorAgent` starts a permanently supervised crashing worker and a stable
worker. The crashing worker is cleaned up and restarted until the supervisor's
restart threshold escalates.
