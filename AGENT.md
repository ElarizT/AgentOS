# AGENTS.md - Context for Codex Engineering Agent

## Project Objective
We are building a highly concurrent, production-grade Agent OS Kernel.
- **Core Kernel:** Written in Rust for memory safety, speed, and thread-safe IPC.
- **Interface:** Exposed to Python via PyO3 and Maturin as `agent_os_core`.

## Architectural Rules
1. **Thread Safety First:** The Rust state registry must use `Arc<Mutex<T>>` or lock-free structures. Never expose unsafe blocks to the Python layer.
2. **Asynchronous Runtime:** The IPC message bus should utilize Rust's `tokio` channels for high-throughput message queuing, bridging natively into Python's `asyncio` loop.
3. **Zero-Copy Goals:** Where possible, design text context transfers using memory maps or shared pointers rather than duplicating large strings.

## Commands for the Iteration Loop
- Build and Install Extension: `maturin develop`
- Run Python Tests: `python -m pytest tests/`