use serde::Serialize;
use std::sync::{Mutex, OnceLock};
use sysinfo::{CpuRefreshKind, MemoryRefreshKind, RefreshKind, System};

#[derive(Serialize)]
pub struct SystemMetrics {
    pub cpu_percent: f32,
    pub memory_used_bytes: u64,
    pub memory_total_bytes: u64,
}

// Reuse sysinfo's CPU sampling history. Creating a fresh System every poll
// causes the first CPU sample to be misleading and repeats expensive discovery.
static SYSTEM: OnceLock<Mutex<System>> = OnceLock::new();

pub fn snapshot() -> SystemMetrics {
    let system = SYSTEM.get_or_init(|| {
        Mutex::new(System::new_with_specifics(
            RefreshKind::nothing()
                .with_cpu(CpuRefreshKind::everything())
                .with_memory(MemoryRefreshKind::everything()),
        ))
    });
    let mut sys = system
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    sys.refresh_cpu_all();
    sys.refresh_memory();
    SystemMetrics {
        cpu_percent: sys.global_cpu_usage(),
        memory_used_bytes: sys.used_memory(),
        memory_total_bytes: sys.total_memory(),
    }
}
