# Agent OS SDK Quickstart

Build and run your first Agent OS process in about 15 minutes.

## 1. Start Agent OS

Set up the project and native extension as described in
`docs/windows_dev_setup.md`, then launch the dashboard:

```powershell
python main.py
```

The dashboard shell accepts:

```text
run <path>
ps
kill <PID>
help
```

## 2. Write an Agent

Create a Python file under the workspace root:

```python
from agentos import AgentProcess


class HelloAgent(AgentProcess):
    name = "HelloAgent"

    async def on_start(self) -> None:
        self.remember({"message": "Hello from Agent OS"}, tags=["hello"])
```

Run it from the dashboard:

```text
run examples/hello_agent.py
ps
```

`from agentos import AgentProcess` is the public SDK import. Existing agents
that use `from kernel.process import AgentProcess` remain supported for
backward compatibility.

## Lifecycle Methods

Override the hooks you need:

```python
from agentos import AgentProcess


class LifecycleAgent(AgentProcess):
    name = "LifecycleAgent"

    async def on_start(self) -> None:
        self.remember({"event": "started"})

    async def on_message(self, message) -> None:
        self.remember({"event": "message", "payload": message.payload})

    async def on_stop(self) -> None:
        self.remember({"event": "stopped"})
```

| Method | Called when |
| --- | --- |
| `on_start()` | The process starts, before mailbox processing begins |
| `on_message(message)` | A structured IPC message arrives |
| `on_stop()` | A started process shuts down cleanly |

## Structured IPC

Messages are validated protocol envelopes. Use PID-based helpers rather than
constructing transport messages by hand.

```python
self.send(target_pid, {"event": "ready"}, message_type="event")
message = await self.receive(timeout=1.0)
response = await self.request(target_pid, {"question": "ping"}, timeout=2.0)
self.reply(request_message, {"answer": "pong"})
```

| Helper | Purpose |
| --- | --- |
| `send(target_pid, payload, ...)` | Send a one-way structured message |
| `receive(timeout=...)` | Wait for the next structured message |
| `request(target_pid, payload, timeout=...)` | Send a request and wait for its correlated response |
| `reply(request_message, payload)` | Reply while preserving the request correlation ID |
| `emit(event_name, payload)` | Emit a low-priority event to PID `1` when that control-plane target exists |

See `examples/ipc_ping_pong_quickstart.py` for a runnable request/reply example:

```text
run examples/ipc_ping_pong_quickstart.py
```

## Persistent Memory

Trusted agents can store and recall process-local records:

```python
self.remember(
    {"fact": "Agent OS memory is process-local"},
    importance=0.8,
    tags=["project"],
)
records = self.recall(query="process-local", tags=["project"], limit=5)
stats = self.memory_stats()
```

Memory records move from hot context to warm memory and cold JSONL persistence
when the token budget is exceeded. Recall is scoped to the current process.
See `examples/memory_agent.py`.

## Supervisor Trees

A trusted process can launch supervised children:

```python
from agentos import AgentProcess


class Supervisor(AgentProcess):
    name = "Supervisor"
    supervisor_strategy = "one_for_one"

    async def on_start(self) -> None:
        worker_pid = await self.spawn_child(
            "examples/worker.py",
            restart_policy="permanent",
        )
        self.monitor_child(worker_pid)
```

`spawn_child()` automatically links the child to its parent. Available restart
policies are `permanent`, `transient`, and `temporary`. Available strategies
are `one_for_one`, `one_for_all`, and `rest_for_one`.

Run the small restart example:

```text
run examples/supervisor_quickstart.py
ps
```

## Trusted vs Isolated Mode

Trusted local mode is the default:

```powershell
$env:AGENT_OS_PROCESS_ISOLATION = "in-process"
python main.py
```

Use spawned subprocess isolation when agents should execute separately:

```powershell
$env:AGENT_OS_PROCESS_ISOLATION = "process"
python main.py
```

| Mode | Best for | Notes |
| --- | --- | --- |
| `in-process` | Development, supervisors, persistent-memory agents | Full registry attachment; supports child spawning and host-backed recall |
| `process` | Isolated workers | Windows-safe `multiprocessing` spawn with queue-bridged IPC; not a complete security sandbox |

An isolated child receives local memory accounting and queue-backed IPC. The
host remains authoritative for routing, lifecycle, supervision, and telemetry.

## Start from the Template

Use `templates/basic_agent.py` as a copyable starting point. It includes
startup memory and request/reply handling without extra framework code.

## Common Errors

| Error | Fix |
| --- | --- |
| `agent script must define an AgentProcess subclass` | Add `class MyAgent(AgentProcess): ...` |
| `agent process must define a unique non-empty name` | Add a class-level name such as `name = "MyAgent"` |
| `agent script import is not allowed` | Keep agent scripts dependency-light. Start with `from agentos import AgentProcess`. |
| `mailbox_size must be a positive integer` | Set a positive integer, for example `mailbox_size = 128`. |
| `token_budget must be a positive integer` | Set a positive integer, for example `token_budget = 8000`. |
| `agent process crashed during startup` | Check the underlying validation or `on_start()` traceback. In isolated mode the host reports the child failure. |
| `target_not_found` | Confirm the target PID with `ps`; restarted children receive a new PID. |
| `mailbox_full` | The receiver is backpressured. Drain work or increase its mailbox size. |

## Public SDK Surface

The stable `agentos` facade exports:

- `AgentProcess`
- `ExecutionMode`
- `RestartPolicy`
- `SupervisorStrategy`
- structured IPC message classes
- `make_message`, `parse_message`, and `make_error`

Kernel modules remain available for internal use and backward compatibility,
but new agent code should import from `agentos`.
