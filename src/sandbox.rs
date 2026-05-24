use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};
use wasmtime::{Config, Engine, Func, Instance, Linker, Module, Store, Val, ValType};
use wasmtime_wasi::pipe::MemoryOutputPipe;
use wasmtime_wasi::preview1::{self, WasiP1Ctx};
use wasmtime_wasi::WasiCtxBuilder;

const MAX_LINEAR_MEMORY_BYTES: usize = 32 * 1024 * 1024;
const STDOUT_CAPTURE_BYTES: usize = 1024 * 1024;

#[pyclass]
#[derive(Clone, Debug)]
pub struct WasmExecutionResult {
    #[pyo3(get)]
    pub success: bool,
    #[pyo3(get)]
    pub stdout: String,
    #[pyo3(get)]
    pub error_message: Option<String>,
    #[pyo3(get)]
    pub fuel_consumed: u64,
}

#[pymethods]
impl WasmExecutionResult {
    #[new]
    pub fn new(
        success: bool,
        stdout: String,
        fuel_consumed: u64,
        error_message: Option<String>,
    ) -> Self {
        Self {
            success,
            stdout,
            error_message,
            fuel_consumed,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "WasmExecutionResult(success={}, fuel_consumed={}, error_message={:?})",
            self.success, self.fuel_consumed, self.error_message
        )
    }
}

#[pyclass]
#[derive(Clone)]
pub struct WasmSandboxManager {
    engine: Arc<Engine>,
    execution_log: Arc<Mutex<Vec<WasmExecutionRecord>>>,
}

#[pymethods]
impl WasmSandboxManager {
    #[new]
    pub fn new() -> PyResult<Self> {
        Ok(Self {
            engine: Arc::new(build_engine()?),
            execution_log: Arc::new(Mutex::new(Vec::new())),
        })
    }

    pub fn execute_wasm_binary(
        &self,
        wasm_bytes: &Bound<'_, PyBytes>,
        fuel_limit: u64,
    ) -> PyResult<WasmExecutionResult> {
        if fuel_limit == 0 {
            return Err(PyValueError::new_err("fuel_limit must be greater than zero"));
        }

        let module = match Module::from_binary(&self.engine, wasm_bytes.as_bytes()) {
            Ok(module) => module,
            Err(err) => {
                let result = WasmExecutionResult::failure(
                    String::new(),
                    format!("CompileError: {err}"),
                    0,
                );
                self.record_execution(&result)?;
                return Ok(result);
            }
        };

        let stdout_pipe = MemoryOutputPipe::new(STDOUT_CAPTURE_BYTES);
        let wasi_ctx = build_wasi_context(stdout_pipe.clone());
        let mut store = Store::new(&self.engine, wasi_ctx);
        store
            .set_fuel(fuel_limit)
            .map_err(|err| PyRuntimeError::new_err(format!("failed to set fuel: {err}")))?;

        let result = run_module(&self.engine, &module, &mut store);
        let fuel_consumed = fuel_consumed(&store, fuel_limit);
        let stdout_bytes = stdout_pipe.contents();
        let stdout = String::from_utf8_lossy(&stdout_bytes).to_string();

        let execution_result = match result {
            Ok(()) => WasmExecutionResult {
                success: true,
                stdout,
                error_message: None,
                fuel_consumed,
            },
            Err(err) => WasmExecutionResult::failure(
                stdout,
                classify_execution_error(&err),
                fuel_consumed,
            ),
        };

        self.record_execution(&execution_result)?;
        Ok(execution_result)
    }

    pub fn get_execution_metrics(&self) -> PyResult<Vec<(u64, bool, u64, Option<String>)>> {
        let log = self
            .execution_log
            .lock()
            .map_err(|err| PyRuntimeError::new_err(format!("sandbox metrics lock poisoned: {err}")))?;
        Ok(log
            .iter()
            .map(|record| {
                (
                    record.timestamp,
                    record.success,
                    record.fuel_consumed,
                    record.error_message.clone(),
                )
            })
            .collect())
    }
}

impl WasmExecutionResult {
    fn failure(stdout: String, error_message: String, fuel_consumed: u64) -> Self {
        Self {
            success: false,
            stdout,
            error_message: Some(error_message),
            fuel_consumed,
        }
    }
}

#[derive(Clone, Debug)]
struct WasmExecutionRecord {
    timestamp: u64,
    success: bool,
    fuel_consumed: u64,
    error_message: Option<String>,
}

impl WasmSandboxManager {
    fn record_execution(&self, result: &WasmExecutionResult) -> PyResult<()> {
        let mut log = self
            .execution_log
            .lock()
            .map_err(|err| PyRuntimeError::new_err(format!("sandbox metrics lock poisoned: {err}")))?;

        log.push(WasmExecutionRecord {
            timestamp: unix_timestamp(),
            success: result.success,
            fuel_consumed: result.fuel_consumed,
            error_message: result.error_message.clone(),
        });

        if log.len() > 256 {
            let overflow = log.len() - 256;
            log.drain(0..overflow);
        }

        Ok(())
    }
}

fn build_engine() -> PyResult<Engine> {
    let mut config = Config::new();
    config.consume_fuel(true);
    config.async_support(false);
    config.static_memory_maximum_size(MAX_LINEAR_MEMORY_BYTES as u64);

    Engine::new(&config).map_err(|err| PyRuntimeError::new_err(format!("{err}")))
}

fn build_wasi_context(stdout_pipe: MemoryOutputPipe) -> WasiP1Ctx {
    let mut builder = WasiCtxBuilder::new();
    builder.stdout(stdout_pipe);
    builder.build_p1()
}

fn run_module(
    engine: &Engine,
    module: &Module,
    store: &mut Store<WasiP1Ctx>,
) -> Result<(), wasmtime::Error> {
    let mut linker = Linker::new(engine);
    preview1::add_to_linker_sync(&mut linker, |ctx| ctx)?;

    let instance = linker.instantiate(&mut *store, module)?;
    let entrypoint = resolve_entrypoint(store, &instance)?;
    let result_count = entrypoint.ty(&mut *store).results().len();
    let mut results = vec![Val::F32(0); result_count];
    entrypoint.call(store, &[], &mut results)?;

    Ok(())
}

fn resolve_entrypoint(
    store: &mut Store<WasiP1Ctx>,
    instance: &Instance,
) -> Result<Func, wasmtime::Error> {
    for export_name in ["_start", "main", "run"] {
        if let Some(func) = instance.get_func(&mut *store, export_name) {
            ensure_zero_arity(store, &func, export_name)?;
            return Ok(func);
        }
    }

    let fallback_export = {
        let mut fallback = None;
        for export in instance.exports(&mut *store) {
            let export_name = export.name().to_string();
            if let Some(func) = export.into_func() {
                fallback = Some((export_name, func));
                break;
            }
        }
        fallback
    };

    if let Some((export_name, func)) = fallback_export {
        ensure_zero_arity(store, &func, &export_name)?;
        return Ok(func);
    }

    Err(wasmtime::Error::msg(
        "no callable zero-argument default export found",
    ))
}

fn ensure_zero_arity(
    store: &mut Store<WasiP1Ctx>,
    func: &Func,
    export_name: &str,
) -> Result<(), wasmtime::Error> {
    let ty = func.ty(&mut *store);
    let params: Vec<_> = ty.params().collect();
    let results: Vec<_> = ty.results().collect();

    if !params.is_empty() {
        return Err(wasmtime::Error::msg(format!(
            "export '{export_name}' must not require parameters"
        )));
    }

    if results.is_empty() || (results.len() == 1 && matches!(results[0], ValType::F32)) {
        Ok(())
    } else {
        Err(wasmtime::Error::msg(format!(
            "export '{export_name}' must have signature () -> () or () -> f32"
        )))
    }
}

fn fuel_consumed(store: &Store<WasiP1Ctx>, fuel_limit: u64) -> u64 {
    match store.get_fuel() {
        Ok(remaining) => fuel_limit.saturating_sub(remaining),
        Err(_) => 0,
    }
}

fn classify_execution_error(err: &wasmtime::Error) -> String {
    let message = err.to_string();
    let lower = message.to_ascii_lowercase();

    if lower.contains("all fuel consumed") || lower.contains("fuel") {
        "FuelExhausted".to_string()
    } else if lower.contains("out of memory")
        || lower.contains("memory")
        || lower.contains("heap")
        || lower.contains("maximum")
    {
        format!("OutOfMemory: {message}")
    } else {
        format!("Trap: {message}")
    }
}

fn unix_timestamp() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or_default()
}
