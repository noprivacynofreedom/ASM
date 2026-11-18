use serde::Serialize;
use std::collections::HashMap;
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

/// Live load of one GPU. `None` means "not measured", never zero.
#[derive(Serialize, Clone, Debug, PartialEq)]
pub struct GpuLive {
    pub name: String,
    pub vendor: String,
    pub utilization_percent: Option<f64>,
    pub vram_used_mb: Option<u64>,
    pub vram_total_mb: Option<u64>,
    pub source: String,
}

/// One adapter from DXGI: name, vendor, "luid_0x..._0x..." key, dedicated VRAM.
#[derive(Clone, Debug)]
pub struct Adapter {
    pub name: String,
    pub vendor: String,
    pub luid: String,
    pub vram_total_mb: Option<u64>,
}

/// "...luid_0x00000000_0x0000D1E3_phys_0_eng_3_engtype_3D" -> ("luid_0x00000000_0x0000D1E3", Some("eng_3")).
fn luid_and_engine(instance: &str) -> Option<(String, Option<String>)> {
    let lower = instance.to_ascii_lowercase();
    let start = lower.find("luid_")?;
    let luid: String = lower[start..].splitn(4, '_').take(3).collect::<Vec<_>>().join("_");
    let engine = lower
        .find("_eng_")
        .map(|i| lower[i + 1..].splitn(3, '_').take(2).collect::<Vec<_>>().join("_"));
    Some((luid, engine))
}

/// Task Manager's method: add up every process on one engine, the GPU % is the busiest engine.
/// `engines` = (instance, percent) from "GPU Engine(*)\Utilization Percentage".
/// `memory` = (instance, bytes) from "GPU Adapter Memory(*)\Dedicated Usage".
pub fn aggregate(adapters: &[Adapter], engines: &[(String, f64)], memory: &[(String, f64)]) -> Vec<GpuLive> {
    let mut per_engine: HashMap<(String, String), f64> = HashMap::new();
    for (inst, v) in engines {
        if let Some((luid, Some(eng))) = luid_and_engine(inst) {
            *per_engine.entry((luid, eng)).or_default() += v.max(0.0);
        }
    }
    let mut used: HashMap<String, f64> = HashMap::new();
    for (inst, v) in memory {
        if let Some((luid, _)) = luid_and_engine(inst) {
            *used.entry(luid).or_default() += v.max(0.0);
        }
    }
    adapters
        .iter()
        .map(|a| {
            let busiest = per_engine
                .iter()
                .filter(|((l, _), _)| *l == a.luid)
                .map(|(_, v)| *v)
                .fold(None, |m: Option<f64>, v| Some(m.map_or(v, |m| m.max(v))));
            GpuLive {
                name: a.name.clone(),
                vendor: a.vendor.clone(),
                utilization_percent: busiest.map(|v| v.min(100.0)),
                vram_used_mb: used.get(&a.luid).map(|b| (*b as u64) / (1024 * 1024)),
                vram_total_mb: a.vram_total_mb,
                source: "Windows GPU performance counters".into(),
            }
        })
        .collect()
}

#[cfg(windows)]
mod pdh {
    use super::Adapter;
    use windows_sys::Win32::System::Performance::*;

    pub struct Query {
        query: PDH_HQUERY,
        engine: PDH_HCOUNTER,
        memory: PDH_HCOUNTER,
        pub adapters: Vec<Adapter>,
    }
    // The handles are only used while the Mutex in gpu_live() is held.
    unsafe impl Send for Query {}

    fn wide(s: &str) -> Vec<u16> {
        s.encode_utf16().chain(std::iter::once(0)).collect()
    }

    impl Query {
        pub fn open() -> Option<Query> {
            let mut q = Query {
                query: std::ptr::null_mut(),
                engine: std::ptr::null_mut(),
                memory: std::ptr::null_mut(),
                adapters: adapters(),
            };
            unsafe {
                if PdhOpenQueryW(std::ptr::null(), 0, &mut q.query) != 0 {
                    return None;
                }
                let e = wide(r"\GPU Engine(*)\Utilization Percentage");
                let m = wide(r"\GPU Adapter Memory(*)\Dedicated Usage");
                if PdhAddEnglishCounterW(q.query, e.as_ptr(), 0, &mut q.engine) != 0
                    || PdhAddEnglishCounterW(q.query, m.as_ptr(), 0, &mut q.memory) != 0
                {
                    PdhCloseQuery(q.query);
                    return None;
                }
                // Utilization is a rate: the first sample only sets the start point.
                PdhCollectQueryData(q.query);
            }
            Some(q)
        }

        pub fn collect(&mut self) -> bool {
            unsafe { PdhCollectQueryData(self.query) == 0 }
        }

        pub fn read(&self, engine: bool) -> Vec<(String, f64)> {
            let counter = if engine { self.engine } else { self.memory };
            let (mut size, mut count) = (0u32, 0u32);
            unsafe {
                if PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE, &mut size, &mut count, std::ptr::null_mut())
                    != PDH_MORE_DATA
                {
                    return Vec::new();
                }
                // u64 storage keeps the item array 8-byte aligned.
                let mut buf = vec![0u64; (size as usize).div_ceil(8)];
                let items = buf.as_mut_ptr() as *mut PDH_FMT_COUNTERVALUE_ITEM_W;
                if PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE, &mut size, &mut count, items) != 0 {
                    return Vec::new();
                }
                (0..count as usize)
                    .filter_map(|i| {
                        let it = &*items.add(i);
                        if it.FmtValue.CStatus != 0 || it.szName.is_null() {
                            return None;
                        }
                        let len = (0..).take_while(|&k| *it.szName.add(k) != 0).count();
                        let name = String::from_utf16_lossy(std::slice::from_raw_parts(it.szName, len));
                        Some((name, it.FmtValue.Anonymous.doubleValue))
                    })
                    .collect()
            }
        }
    }

    fn adapters() -> Vec<Adapter> {
        use windows::Win32::Graphics::Dxgi::{CreateDXGIFactory1, IDXGIFactory1};
        let mut out = Vec::new();
        let Ok(factory) = (unsafe { CreateDXGIFactory1::<IDXGIFactory1>() }) else {
            return out;
        };
        for index in 0..32u32 {
            let Ok(adapter) = (unsafe { factory.EnumAdapters1(index) }) else { break };
            let Ok(d) = (unsafe { adapter.GetDesc1() }) else { continue };
            let vendor = match d.VendorId {
                0x1002 => "AMD",
                0x10DE => "NVIDIA",
                0x8086 => "Intel",
                _ => continue, // skips "Microsoft Basic Render Driver"
            };
            let end = d.Description.iter().position(|&c| c == 0).unwrap_or(d.Description.len());
            let bytes = d.DedicatedVideoMemory as u64;
            out.push(Adapter {
                name: String::from_utf16_lossy(&d.Description[..end]).trim().to_string(),
                vendor: vendor.into(),
                luid: format!("luid_0x{:08x}_0x{:08x}", d.AdapterLuid.HighPart as u32, d.AdapterLuid.LowPart),
                vram_total_mb: (bytes > 0).then_some(bytes / (1024 * 1024)),
            });
        }
        // Biggest VRAM first, so the UI's first card is the discrete GPU.
        out.sort_by(|a, b| b.vram_total_mb.cmp(&a.vram_total_mb));
        out
    }
}

/// Live GPU load and VRAM use. Cheap: one PDH query is opened once and re-read per call.
/// The utilization is the average since the previous call, so the poll interval is the window.
pub fn gpu_live() -> Result<Vec<GpuLive>, String> {
    #[cfg(windows)]
    {
        static QUERY: OnceLock<Mutex<Option<pdh::Query>>> = OnceLock::new();
        let mut guard = QUERY
            .get_or_init(|| Mutex::new(pdh::Query::open()))
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let q = guard
            .as_mut()
            .ok_or("Windows GPU performance counters are not available on this PC")?;
        if !q.collect() {
            return Err("GPU counters did not answer".into());
        }
        Ok(aggregate(&q.adapters, &q.read(true), &q.read(false)))
    }
    #[cfg(not(windows))]
    {
        Err("Live GPU telemetry is only built for Windows".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn busiest_engine_wins_and_processes_add_up() {
        let a = vec![Adapter { name: "RX 9070 XT".into(), vendor: "AMD".into(), luid: "luid_0x00000000_0x0000d1e3".into(), vram_total_mb: Some(16304) }];
        let engines = vec![
            ("pid_10_luid_0x00000000_0x0000D1E3_phys_0_eng_0_engtype_3D".to_string(), 20.0),
            ("pid_11_luid_0x00000000_0x0000D1E3_phys_0_eng_0_engtype_3D".to_string(), 15.0),
            ("pid_12_luid_0x00000000_0x0000D1E3_phys_0_eng_5_engtype_Compute_0".to_string(), 30.0),
            ("pid_13_luid_0x00000000_0x0000AAAA_phys_0_eng_0_engtype_3D".to_string(), 99.0),
        ];
        let mem = vec![("luid_0x00000000_0x0000D1E3_phys_0".to_string(), 2048.0 * 1024.0 * 1024.0)];
        let g = &aggregate(&a, &engines, &mem)[0];
        assert_eq!(g.utilization_percent, Some(35.0)); // eng_0: 20+15 beats eng_5: 30; other GPU ignored
        assert_eq!(g.vram_used_mb, Some(2048));
        assert_eq!(g.vram_total_mb, Some(16304));
    }

    /// Reads this PC's real counters. Run by hand: cargo test live_gpu -- --ignored --nocapture
    #[test]
    #[ignore]
    fn live_gpu_read() {
        let _ = gpu_live();
        std::thread::sleep(std::time::Duration::from_secs(1));
        let t = std::time::Instant::now();
        let g = gpu_live().expect("GPU counters");
        println!("{g:#?}\none read took {:?}", t.elapsed());
        assert!(g.iter().any(|x| x.utilization_percent.is_some() && x.vram_used_mb.is_some()));
    }

    #[test]
    fn no_samples_means_unknown_not_zero() {
        let a = vec![Adapter { name: "x".into(), vendor: "AMD".into(), luid: "luid_0x00000000_0x00000001".into(), vram_total_mb: None }];
        let g = &aggregate(&a, &[], &[])[0];
        assert_eq!(g.utilization_percent, None);
        assert_eq!(g.vram_used_mb, None);
    }
}
