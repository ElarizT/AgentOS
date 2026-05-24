use pyo3::prelude::*;

mod ipc;
mod memory;
mod sandbox;

pub use ipc::{AgentMessage, NativeIPCBus, RustKernel};
pub use memory::{ContextMemoryManager, MemoryPage};
pub use sandbox::{WasmExecutionResult, WasmSandboxManager};

#[pymodule]
fn agent_os_core(_py: Python<'_>, module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<AgentMessage>()?;
    module.add_class::<RustKernel>()?;
    module.add_class::<NativeIPCBus>()?;
    module.add_class::<MemoryPage>()?;
    module.add_class::<ContextMemoryManager>()?;
    module.add_class::<WasmExecutionResult>()?;
    module.add_class::<WasmSandboxManager>()?;
    Ok(())
}
