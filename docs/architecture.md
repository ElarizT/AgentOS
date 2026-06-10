# Agent OS Architecture

Agent OS is a hybrid Python/Rust runtime for dynamically loaded agents. Python
owns orchestration, process lifecycle, structured IPC semantics, supervision,
persistent memory, and the terminal dashboard. Rust provides the native mailbox
transport, capability registry, and WASM sandbox exposed to Python through a
PyO3 extension module named `agent_os_core`.

The default runtime boots a control plane and waits for operators to start
`AgentProcess` scripts from the dashboard shell. An optional legacy mode also
starts manifest-backed LLM hosts and an orchestration router.

## Component Hierarchy

```mermaid
flowchart TD
    OP["Operator"] --> APP["main.py<br/>Python host runtime"]

    subgraph Python["Python control plane"]
        APP --> DASH["kernel/dashboard.py<br/>Textual dashboard and shell"]
        APP --> REG["kernel/process.py<br/>ProcessRegistry"]
        APP --> PMEM["kernel/memory_store.py<br/>PersistentMemoryManager"]
        SDK["agentos/__init__.py<br/>Stable public SDK facade"] --> ASDK["kernel/process.py<br/>AgentProcess SDK"]
        REG --> ASDK
        REG --> PROTO["kernel/ipc_protocol.py<br/>Validated IPC envelopes"]
        REG --> RUNNER["kernel/process_runner.py<br/>Isolated child runner"]
        APP -. optional .-> LLM["kernel/llm/<br/>Provider-neutral runtime and legacy manager"]
        APP -. optional .-> TOOL["kernel/toolchain.py<br/>Restricted Python-to-WASM compiler"]
    end

    subgraph Rust["Rust extension: agent_os_core"]
        LIB["src/lib.rs<br/>PyO3 module exports"]
        IPC["src/ipc.rs<br/>RustKernel and NativeIPCBus"]
        RMEM["src/memory.rs<br/>ContextMemoryManager"]
        WASM["src/sandbox.rs<br/>WasmSandboxManager"]
        LIB --> IPC
        LIB --> RMEM
        LIB --> WASM
    end

    APP --> IPC
    APP --> WASM
    TOOL -. WASM bytes .-> WASM
    REG --> IPC
    DASH --> IPC
    DASH --> PMEM
    DASH --> WASM
    RUNNER --> CHILD["Spawned Python child process"]
```

### Runtime Ownership

| Concern | Primary owner | Notes |
| --- | --- | --- |
| Boot, shutdown, shell commands | `main.py` | Creates shared services and runs dashboard tasks. |
| Dynamic process records | `kernel/process.py` | PID allocation, lifecycle, cleanup, supervision, telemetry snapshots. |
| Structured IPC protocol | `kernel/ipc_protocol.py` | Protocol `0.1`, message types, validation, JSON serialization, errors. |
| Mailbox transport | `src/ipc.rs` | Tokio bounded channels, direct and capability fallback routing, metrics. |
| Persistent process memory | `kernel/memory_store.py` | Hot/warm/cold records, JSONL persistence, snapshots, deterministic recall. |
| Native page-table primitive | `src/memory.rs` | Separate Rust-exported in-memory paging API. It is not the active process registry store. |
| Isolated subprocess adapter | `kernel/process_runner.py` | Spawn-safe runner, queue bridge endpoints, local `IsolatedMemory`. |
| WASM execution | `src/sandbox.rs` | Wasmtime engine, fuel accounting, memory limit, execution metrics. |
| Dashboard telemetry | `kernel/dashboard.py` | Polls bus, memory, sandbox, and process snapshots every `0.1` seconds. |

## Runtime Lifecycle

```mermaid
sequenceDiagram
    participant OS as Operator / OS
    participant Main as main.py
    participant Rust as agent_os_core
    participant Mem as PersistentMemoryManager
    participant Reg as ProcessRegistry
    participant Dash as AgentOSDashboard

    OS->>Main: python main.py
    Main->>Rust: RustKernel()
    Main->>Rust: NativeIPCBus(kernel)
    Main->>Mem: PersistentMemoryManager(memory_dir)
    Main->>Rust: WasmSandboxManager()
    Main->>Rust: register control-plane mailboxes
    Main->>Reg: ProcessRegistry(kernel, bus, memory, config)
    Main->>Dash: AgentOSDashboard(..., command_handler, process_snapshot)
    Main->>Dash: run_async()
    Main->>Main: optional_stdin_ingress()

    opt AGENT_OS_ENABLE_LEGACY_AGENTS=1
        Main->>Main: load manifest and DynamicAgentRegistry
        Main->>Rust: register manifest mailboxes and capabilities
        Main->>Main: start orchestration_router and universal_agent_host tasks
    end

    OS->>Dash: run / ps / kill
    Dash->>Main: handle_shell_command(command)
    Main->>Reg: lifecycle operation
    Reg-->>Dash: status text or process snapshots

    OS->>Main: SIGINT or dashboard exit
    Main->>Reg: stop managed work
    Main->>Rust: shutdown native services
```

The standard boot path constructs:

1. `RustKernel`
2. `NativeIPCBus`
3. Python `PersistentMemoryManager`
4. Rust `WasmSandboxManager`
5. Control-plane mailboxes
6. `ProcessRegistry`
7. `AgentOSDashboard`

`AGENT_OS_PROCESS_ISOLATION` selects the default execution mode for dynamic
agents: `in-process` or spawned child `process` mode.

## Process Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Validating: run_path(path)
    Validating --> Starting: path, AST, metadata valid
    Validating --> Rejected: invalid path or script

    Starting --> Running: transactional registration committed
    Starting --> Rejected: startup registration fails
    Starting --> Crashed: isolated child reports startup crash

    Running --> Stopping: kill(pid)
    Running --> Exited: run() returns normally
    Running --> Crashed: exception or child process failure
    Stopping --> Killed: cleanup complete

    Exited --> RestartEvaluation: supervised child
    Crashed --> RestartEvaluation: supervised child
    RestartEvaluation --> Starting: policy and restart budget allow replacement
    RestartEvaluation --> Terminal: temporary, transient normal exit, no parent, or escalation

    Killed --> Terminal
    Rejected --> [*]
    Terminal --> [*]
```

### Startup Transaction

`ProcessRegistry.run_path()` resolves and validates the script under
`AGENT_OS_PROCESS_ROOT`, restricts imports, allocates a PID, and registers
runtime resources. Registration is transactional:

```mermaid
flowchart LR
    A["Allocate ProcessRecord"] --> B["Register bus mailbox"]
    B --> C["Register memory table"]
    C --> D["Bind memory owner PID"]
    D --> E["Register capabilities"]
    E --> F["Attach process SDK"]
    F --> G["Insert PID and name indexes"]
    G --> H["Emit process_started"]

    B -. failure .-> R["Rollback partial startup"]
    C -. failure .-> R
    D -. failure .-> R
    E -. failure .-> R
    F -. failure .-> R
    G -. failure .-> R
    R --> X["Remove mailbox, memory, kernel registration,<br/>PID/name indexes, parent link, and telemetry"]
```

Runtime cleanup intentionally differs from startup rollback. A crashed, exited,
or killed process keeps its `ProcessRecord` so `ps` and the dashboard can show
terminal state and error context, while active mailbox, memory table, and kernel
capabilities are unregistered.

### Execution Modes

```mermaid
flowchart TD
    REG["ProcessRegistry"] --> MODE{"Execution mode"}
    MODE -->|in-process| TASK["asyncio task<br/>AgentProcess.run()"]
    MODE -->|isolated| SPAWN["multiprocessing spawn"]
    SPAWN --> READY["Child validates script and sends ready metadata"]
    READY --> MON["Host monitor task"]
    MON --> BRIDGE["Mailbox-to-queue IPC bridge"]
    BRIDGE <--> CHILD["kernel/process_runner.py<br/>IsolatedBus and IsolatedMemory"]
```

Trusted in-process agents receive the full registry attachment and can spawn or
monitor children. Isolated agents run in a separate Python process with a
minimal environment and queue-backed bus adapter. Process mode is isolation,
not a complete security sandbox.

## IPC Flow

Structured IPC is a Python protocol layered on the Rust mailbox transport.
Every envelope includes source and target PIDs, protocol version, message ID,
optional correlation ID, timestamp, priority, payload, and optional expiry.

```mermaid
sequenceDiagram
    participant A as AgentProcess A
    participant Reg as ProcessRegistry
    participant Proto as ipc_protocol.py
    participant Bus as NativeIPCBus
    participant B as AgentProcess B

    A->>Proto: make_message(task_request, correlation_id, ttl)
    A->>Reg: route_ipc_message(envelope)
    Reg->>Proto: validate size, PID shape, type, priority, expiry
    Reg->>Reg: verify source and target ProcessRecord state
    Reg->>Bus: send_message(AgentMessage(name, name, JSON))
    Bus->>Bus: bounded Tokio try_send()
    Bus-->>B: recv_message(target name)
    B->>Proto: parse_message(JSON)
    B->>Reg: reply(request, payload)
    Reg->>Bus: send task_response with same correlation_id
    Bus-->>A: recv_message(source name)
    A->>A: request() matches correlation_id
```

Routing failures return structured `ErrorMessage` values. Important protocol
codes include `target_not_found`, `mailbox_full`, `timeout`, `invalid_message`,
`process_dead`, and `payload_too_large`. Mailbox backpressure is preserved as
`mailbox_full`; it is not collapsed into generic validation failure.

### Isolated IPC Bridge

```mermaid
flowchart LR
    SRC["Host or agent"] --> REG["ProcessRegistry.route_ipc_message()"]
    REG --> BUS["NativeIPCBus target mailbox"]
    BUS --> MON["Host monitor task"]
    MON --> IN["multiprocessing child_inbox"]
    IN --> IBUS["IsolatedBus.recv_message()"]
    IBUS --> CHILD["Isolated AgentProcess"]
    CHILD --> OBUS["IsolatedBus.send_message()"]
    OBUS --> OUT["multiprocessing child_outbox"]
    OUT --> BRIDGE["ProcessRegistry._bridge_child_ipc()"]
    BRIDGE --> REG
```

The host remains authoritative for PID routing and telemetry. Isolated
processes exchange serialized envelopes through queues; the host reparses and
routes outbound envelopes through the same registry path used by trusted
agents.

## Supervision Flow

Agents form parent-child trees through `spawn_child()`. The registry owns tree
links, crash detection, restart policy evaluation, restart limits, cleanup, and
structured supervision events.

```mermaid
flowchart TD
    FAIL["Child crashes or exits"] --> CLEAN["Unregister active resources"]
    CLEAN --> EVENT["Emit process_crashed or process_stopped"]
    EVENT --> PARENT{"Running parent exists?"}
    PARENT -->|no| DONE["Keep terminal record"]
    PARENT -->|yes| STRAT{"Supervisor strategy"}
    STRAT -->|one_for_one| ONE["Failed child"]
    STRAT -->|one_for_all| ALL["All children"]
    STRAT -->|rest_for_one| REST["Failed child and later siblings"]
    ONE --> POLICY
    ALL --> POLICY
    REST --> POLICY
    POLICY{"Restart policy allows restart?"}
    POLICY -->|no| DONE
    POLICY -->|yes| BUDGET{"Within restart budget?"}
    BUDGET -->|no| ESC["Mark escalation and emit supervision_escalation"]
    BUDGET -->|yes| BACKOFF["Apply restart backoff"]
    BACKOFF --> RESTART["Start replacement PID"]
    RESTART --> MEM["Apply memory restore policy"]
    MEM --> LINK["Replace child link and deduplicate tree"]
    LINK --> NOTIFY["Emit child_restarted event"]
```

Supported supervisor strategies:

| Strategy | Restart set |
| --- | --- |
| `one_for_one` | Failed child only |
| `one_for_all` | Every child |
| `rest_for_one` | Failed child and siblings started after it |

Supported child restart policies:

| Policy | Behavior |
| --- | --- |
| `permanent` | Restart on normal exit or crash |
| `transient` | Restart only after abnormal failure |
| `temporary` | Never restart |

Restart storms are bounded by `max_restarts` within
`restart_window_seconds`. `restart_backoff_seconds` delays replacement
attempts. Parent termination cascades to live descendants.

## Memory Flow

The active dynamic-process store is Python `PersistentMemoryManager`.
`AgentProcess.remember()`, `recall()`, `forget()`, and `memory_stats()` delegate
to this manager when the agent runs in trusted mode.

```mermaid
flowchart TD
    AGENT["AgentProcess.remember(content, tags, importance)"] --> HOT["Hot records<br/>active per-process context"]
    HOT --> LIMIT{"Token budget exceeded?"}
    LIMIT -->|no| STAY["Remain hot"]
    LIMIT -->|yes| PICK["Select low-importance / least-recent record"]
    PICK --> WARM["Warm records<br/>bounded in-memory cache"]
    PICK --> COLD["Cold JSONL index<br/>memories.jsonl"]

    QUERY["AgentProcess.recall(query, tags, limit)"] --> SCOPE["Process-local candidate scope"]
    SCOPE --> FILTER["Tag and substring filtering"]
    FILTER --> SORT["Importance then recency ordering"]
    SORT --> RESULT["Memory records"]

    SNAP["registry.snapshot_process(pid)"] --> FILE["snapshots/*.json"]
    FILE --> RESTORE["Restart restore policy"]
    RESTORE --> HOT
```

Persistent recall is scoped by `process_name`; one process does not search
another process's records. Cold records are stored in
`.agent_os/memory/memories.jsonl` by default. Snapshot files contain hot
records, warm/cold references, token usage, timestamp, PID, and process name.

Supported supervised restart restore policies:

| Policy | Behavior |
| --- | --- |
| `none` | Start with a fresh active table |
| `hot_only` | Restore hot snapshot records only |
| `latest_snapshot` | Restore latest or explicitly tracked snapshot |
| `persistent_recall` | Recall persisted records and append them to the replacement table |

### Memory Boundaries

```mermaid
flowchart LR
    TRUSTED["Trusted AgentProcess"] --> PMEM["Python PersistentMemoryManager<br/>hot / warm / cold / snapshots"]
    ISOLATED["Isolated AgentProcess"] --> IMEM["IsolatedMemory<br/>local token counter adapter"]
    MAIN["main.py"] --> PMEM
    RUSTAPI["Optional native API consumer"] --> RMEM["Rust ContextMemoryManager<br/>in-memory page tables"]
```

`src/memory.rs` remains a separate Rust-exported native page-table primitive.
The current `main.py` process registry is wired to Python
`PersistentMemoryManager` because supervision restore and disk-backed recall
require the richer persistence API. An isolated child receives a local
`IsolatedMemory` adapter; persistent storage and telemetry remain host-owned.

## Dashboard Integration

```mermaid
flowchart TD
    TIMER["Textual interval<br/>every 0.1 seconds"] --> REFRESH["AgentOSDashboard.refresh_metrics()"]
    REFRESH --> BUS["NativeIPCBus.get_mailbox_metrics()"]
    REFRESH --> MEM["PersistentMemoryManager.list_agents()<br/>and get_page_table_summary()"]
    REFRESH --> WASM["WasmSandboxManager.get_execution_metrics()"]
    REFRESH --> PS["ProcessRegistry.list_processes()"]

    BUS --> IPCPANE["IPC Mailbox Lane Monitor"]
    MEM --> MEMPANE["Page Table Context Visualizer"]
    WASM --> LOG["WASM Execution Shield Matrix / shell log"]
    PS --> PROCPANE["Process Registry table"]

    INPUT["Dashboard shell input"] --> HANDLER["main.py handle_shell_command()"]
    HANDLER --> CMD{"run / ps / kill / help"}
    CMD --> PS
```

The dashboard combines four telemetry sources:

| Pane | Source | Visible signals |
| --- | --- | --- |
| Status bar | Rust kernel and Python memory manager | Registered agents, active tokens, heartbeat |
| IPC monitor | Rust `NativeIPCBus` | Queue depth, capacity, routing method |
| Memory visualizer | Python `PersistentMemoryManager` | Active tokens, active frames, paged frames |
| WASM log | Rust `WasmSandboxManager` and shell handler | Execution status, fuel use, errors, command output |
| Process table | Python `ProcessRegistry` | PID tree, state, mode, parent, children, restart count, strategy, memory, IPC counters |

`ProcessRegistry.list_processes()` reaps finished isolated children before
returning snapshots, keeping dashboard state aligned with subprocess state.

## Rust/Python Boundary

```mermaid
flowchart LR
    subgraph PY["Python"]
        MAIN["main.py"]
        REG["ProcessRegistry"]
        DASH["AgentOSDashboard"]
        TOOL["toolchain.py"]
        PMEM["PersistentMemoryManager"]
    end

    subgraph EXT["PyO3 extension module: agent_os_core"]
        RK["RustKernel"]
        BUS["NativeIPCBus"]
        MSG["AgentMessage"]
        RMEM["ContextMemoryManager"]
        WSM["WasmSandboxManager"]
        WRES["WasmExecutionResult"]
    end

    MAIN --> RK
    MAIN --> BUS
    MAIN --> WSM
    REG --> BUS
    REG --> MSG
    DASH --> RK
    DASH --> BUS
    DASH --> WSM
    TOOL -. compiled bytes .-> WSM
    MAIN --> PMEM
```

`src/lib.rs` exposes these Rust classes:

| Rust export | Python role |
| --- | --- |
| `AgentMessage` | JSON-validated transport envelope used by the native bus |
| `RustKernel` | Registered-agent set, capability map, shutdown flag |
| `NativeIPCBus` | Bounded mailbox registration, send, async receive, queue metrics |
| `MemoryPage` | Native page-table record |
| `ContextMemoryManager` | Native in-memory paging primitive |
| `WasmExecutionResult` | WASM outcome, stdout, error, fuel consumed |
| `WasmSandboxManager` | Wasmtime execution and bounded execution metrics |

The Rust IPC bus owns a Tokio runtime on a dedicated worker thread. Python
receives `asyncio.Future` objects; Rust completes them safely with
`call_soon_threadsafe`. Native mailbox sends use bounded `try_send`, so
backpressure is observable immediately by Python.

The WASM sandbox uses Wasmtime with fuel accounting, a fixed maximum linear
memory size, captured stdout, and no general CPython compatibility layer.
`kernel/toolchain.py` compiles a deliberately small Python AST subset into
standalone WASM bytes.

## Component Dependency Map

```mermaid
flowchart TD
    MAIN["main.py"] --> DASH["kernel/dashboard.py"]
    MAIN --> PROC["kernel/process.py"]
    MAIN --> PMEM["kernel/memory_store.py"]
    MAIN --> LLM["kernel/llm/"]
    MAIN --> TOOL["kernel/toolchain.py"]
    MAIN --> CORE["agent_os_core PyO3 module"]

    PROC --> PROTO["kernel/ipc_protocol.py"]
    SDK["agentos/__init__.py"] --> PROC
    SDK --> PROTO
    PROC --> RUNNER["kernel/process_runner.py"]
    PROC --> CORE
    DASH --> CORE
    DASH --> PMEM
    TOOL -. optional WASM bytes .-> CORE

    CORE --> LIB["src/lib.rs"]
    LIB --> IPC["src/ipc.rs"]
    LIB --> RMEM["src/memory.rs"]
    LIB --> SANDBOX["src/sandbox.rs"]

    RUNNER --> PROC
```

### File-Level Responsibilities

| File | Depends on | Responsibility |
| --- | --- | --- |
| `agentos/__init__.py` | `kernel.process`, `kernel.ipc_protocol` | Stable public SDK facade for agent authors |
| `main.py` | `agent_os_core`, `kernel.dashboard`, `kernel.memory_store`, `kernel.process` | Runtime composition, shell commands, optional legacy orchestration |
| `kernel/process.py` | `kernel.ipc_protocol`, native `AgentMessage` | Agent SDK, process registry, isolation bridge, supervision, process telemetry |
| `kernel/process_runner.py` | `kernel.process` | Spawned child bootstrap and queue-backed adapters |
| `kernel/ipc_protocol.py` | Python standard library | Structured protocol model and validation |
| `kernel/memory_store.py` | Python standard library | Persistent hot/warm/cold memory and snapshots |
| `kernel/dashboard.py` | Textual, Rich | Terminal UI and telemetry rendering |
| `kernel/llm/` | Python standard library, optional legacy provider dependencies | Provider-neutral LLM requests, providers, runtime facade, and structured events |
| `kernel/toolchain.py` | Python AST, optional Python `wasmtime` assembler | Restricted Python-to-WASM compilation |
| `src/lib.rs` | `src/ipc.rs`, `src/memory.rs`, `src/sandbox.rs` | PyO3 extension exports |
| `src/ipc.rs` | Tokio, PyO3, Serde JSON | Native kernel capability registry and mailbox transport |
| `src/memory.rs` | PyO3, Serde JSON | Native in-memory page tables |
| `src/sandbox.rs` | Wasmtime, WASI, PyO3 | WASM execution and telemetry |

## Operational Summary

The runtime has three distinct execution layers:

1. Python control plane: lifecycle, protocol semantics, supervision, persistent
   memory, dashboard.
2. Rust native services: bounded mailbox transport, capability registry, WASM
   execution, optional native page tables.
3. Agent execution: trusted asyncio tasks or isolated spawned Python child
   processes connected through queue bridges.

This separation keeps lifecycle policy inspectable in Python while moving
bounded concurrency and sandbox execution into Rust.
