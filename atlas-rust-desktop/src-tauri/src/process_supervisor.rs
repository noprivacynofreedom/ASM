use std::{
    fs::{File, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex,
    },
    time::Duration,
};

use serde_json::Value;
use tokio::{
    sync::Mutex as AsyncMutex,
    time::{sleep, Instant},
};

#[cfg(windows)]
mod windows_job {
    use std::{
        ffi::OsStr,
        fs::File,
        mem::{size_of, zeroed},
        os::windows::{
            ffi::OsStrExt,
            io::{AsRawHandle, FromRawHandle},
        },
        path::Path,
        ptr::{null, null_mut},
    };
    use windows_sys::core::BOOL;
    use windows_sys::Win32::{
        Foundation::{
            CloseHandle, DuplicateHandle, GetLastError, SetHandleInformation,
            DUPLICATE_SAME_ACCESS, HANDLE, HANDLE_FLAG_INHERIT,
        },
        System::{
            JobObjects::{
                AssignProcessToJobObject, CreateJobObjectW, IsProcessInJob,
                JobObjectExtendedLimitInformation, SetInformationJobObject, TerminateJobObject,
                JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
            },
            Pipes::CreatePipe,
            Threading::{
                CreateProcessW, DeleteProcThreadAttributeList, GetCurrentProcess,
                InitializeProcThreadAttributeList, ResumeThread, TerminateProcess,
                UpdateProcThreadAttribute, WaitForSingleObject, CREATE_NO_WINDOW, CREATE_SUSPENDED,
                EXTENDED_STARTUPINFO_PRESENT, INFINITE, STARTF_USESTDHANDLES, STARTUPINFOEXW,
                STARTUPINFOW,
            },
        },
    };

    const WAIT_OBJECT_0: u32 = 0;
    const WAIT_TIMEOUT: u32 = 258;

    pub struct Job(HANDLE);
    unsafe impl Send for Job {}

    impl Job {
        pub fn create() -> Result<Self, String> {
            unsafe {
                let handle = CreateJobObjectW(null(), null());
                if handle.is_null() {
                    return Err(last_error("CreateJobObjectW"));
                }
                let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = zeroed();
                limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                if SetInformationJobObject(
                    handle,
                    JobObjectExtendedLimitInformation,
                    &limits as *const _ as *const _,
                    size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                ) == 0
                {
                    let error = last_error("SetInformationJobObject(KILL_ON_JOB_CLOSE)");
                    CloseHandle(handle);
                    return Err(error);
                }
                Ok(Self(handle))
            }
        }

        unsafe fn assign_and_verify(&self, process: HANDLE) -> Result<(), String> {
            if AssignProcessToJobObject(self.0, process) == 0 {
                return Err(last_error("AssignProcessToJobObject"));
            }
            let mut in_job: BOOL = 0;
            if IsProcessInJob(process, self.0, &mut in_job) == 0 {
                return Err(last_error("IsProcessInJob"));
            }
            if in_job == 0 {
                return Err(
                    "Windows did not confirm the child process is in Atlas's Job Object.".into(),
                );
            }
            Ok(())
        }

        /// Puts an already-running child (and, by inheritance, everything it starts later)
        /// into this Job Object.
        pub fn assign_child(&self, child: &std::process::Child) -> Result<(), String> {
            unsafe { self.assign_and_verify(child.as_raw_handle() as HANDLE) }
        }

        pub fn terminate_all(&self) {
            unsafe {
                let _ = TerminateJobObject(self.0, 1);
            }
        }
    }

    impl Drop for Job {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }

    pub struct NativeChild {
        process: HANDLE,
    }
    unsafe impl Send for NativeChild {}

    impl NativeChild {
        pub fn has_exited(&mut self) -> Result<bool, String> {
            self.wait_for(0)
        }

        pub fn wait_for(&mut self, milliseconds: u32) -> Result<bool, String> {
            unsafe {
                match WaitForSingleObject(self.process, milliseconds) {
                    WAIT_OBJECT_0 => Ok(true),
                    WAIT_TIMEOUT => Ok(false),
                    _ => Err(last_error("WaitForSingleObject")),
                }
            }
        }

        pub fn terminate_and_wait(&mut self) {
            unsafe {
                let _ = TerminateProcess(self.process, 1);
                let _ = WaitForSingleObject(self.process, INFINITE);
            }
        }
    }

    impl Drop for NativeChild {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.process);
            }
        }
    }

    fn last_error(operation: &str) -> String {
        let code = unsafe { GetLastError() };
        format!(
            "{operation} failed (Windows error {code}): {}",
            std::io::Error::from_raw_os_error(code as i32)
        )
    }

    fn wide(value: &OsStr) -> Vec<u16> {
        value.encode_wide().chain(std::iter::once(0)).collect()
    }

    // Implements the Windows CRT command-line quoting rules, including embedded quotes and trailing slashes.
    fn quote_arg(arg: &std::ffi::OsStr) -> String {
        let value = arg.to_string_lossy();
        if !value.is_empty() && !value.chars().any(|c| c.is_whitespace() || c == '"') {
            return value.into_owned();
        }
        let mut out = String::from("\"");
        let mut slashes = 0usize;
        for ch in value.chars() {
            match ch {
                '\\' => slashes += 1,
                '"' => {
                    out.push_str(&"\\".repeat(slashes * 2 + 1));
                    out.push('"');
                    slashes = 0;
                }
                _ => {
                    out.push_str(&"\\".repeat(slashes));
                    slashes = 0;
                    out.push(ch);
                }
            }
        }
        out.push_str(&"\\".repeat(slashes * 2));
        out.push('"');
        out
    }

    unsafe fn duplicate_inheritable(handle: HANDLE) -> Result<HANDLE, String> {
        let mut duplicate: HANDLE = null_mut();
        if DuplicateHandle(
            GetCurrentProcess(),
            handle,
            GetCurrentProcess(),
            &mut duplicate,
            0,
            1,
            DUPLICATE_SAME_ACCESS,
        ) == 0
        {
            return Err(last_error("DuplicateHandle(inheritable stdio)"));
        }
        Ok(duplicate)
    }

    struct TempHandle(HANDLE);
    impl Drop for TempHandle {
        fn drop(&mut self) {
            unsafe {
                if !self.0.is_null() {
                    CloseHandle(self.0);
                }
            }
        }
    }

    struct AttributeList(*mut std::ffi::c_void);
    impl Drop for AttributeList {
        fn drop(&mut self) {
            unsafe {
                DeleteProcThreadAttributeList(self.0);
            }
        }
    }

    pub fn spawn_python(
        executable: &str,
        args: &[String],
        root: &Path,
        stdout: &File,
        stderr: &File,
        worker_stdin: bool,
        job: &Job,
    ) -> Result<(NativeChild, Option<File>), String> {
        unsafe {
            let stdout_dup = TempHandle(duplicate_inheritable(stdout.as_raw_handle() as HANDLE)?);
            let stderr_dup = TempHandle(duplicate_inheritable(stderr.as_raw_handle() as HANDLE)?);
            let mut stdin_child_guard: Option<TempHandle> = None;
            let stdin_parent_guard: Option<TempHandle>;
            let stdin_child: HANDLE;
            if worker_stdin {
                let mut read_pipe: HANDLE = null_mut();
                let mut write_pipe: HANDLE = null_mut();
                let mut sa = windows_sys::Win32::Security::SECURITY_ATTRIBUTES {
                    nLength: size_of::<windows_sys::Win32::Security::SECURITY_ATTRIBUTES>() as u32,
                    lpSecurityDescriptor: null_mut(),
                    bInheritHandle: 1,
                };
                if CreatePipe(&mut read_pipe, &mut write_pipe, &mut sa, 0) == 0 {
                    return Err(last_error("CreatePipe(worker stdin)"));
                }
                stdin_child_guard = Some(TempHandle(read_pipe));
                let write_guard = TempHandle(write_pipe);
                if SetHandleInformation(write_pipe, HANDLE_FLAG_INHERIT, 0) == 0 {
                    return Err(last_error("SetHandleInformation(worker stdin)"));
                }
                stdin_child = read_pipe;
                stdin_parent_guard = Some(write_guard);
            } else {
                let nul = File::open("NUL")
                    .map_err(|e| format!("Could not open NUL for Python stdin: {e}"))?;
                stdin_child_guard = Some(TempHandle(duplicate_inheritable(
                    nul.as_raw_handle() as HANDLE
                )?));
                stdin_child = stdin_child_guard.as_ref().expect("stdin handle").0;
                stdin_parent_guard = None;
            }

            let mut startup: STARTUPINFOEXW = zeroed();
            startup.StartupInfo.cb = size_of::<STARTUPINFOEXW>() as u32;
            startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
            startup.StartupInfo.hStdInput = stdin_child;
            startup.StartupInfo.hStdOutput = stdout_dup.0;
            startup.StartupInfo.hStdError = stderr_dup.0;

            // Restrict handle inheritance to this child's three standard handles.
            let mut attribute_bytes = 0usize;
            let _ = InitializeProcThreadAttributeList(null_mut(), 1, 0, &mut attribute_bytes);
            if attribute_bytes == 0 {
                return Err(last_error("InitializeProcThreadAttributeList(size)"));
            }
            let mut attribute_storage =
                vec![0usize; (attribute_bytes + size_of::<usize>() - 1) / size_of::<usize>()];
            let attribute_ptr = attribute_storage.as_mut_ptr() as *mut std::ffi::c_void;
            if InitializeProcThreadAttributeList(attribute_ptr, 1, 0, &mut attribute_bytes) == 0 {
                return Err(last_error("InitializeProcThreadAttributeList"));
            }
            let attribute_guard = AttributeList(attribute_ptr);
            let inherited_handles = [stdin_child, stdout_dup.0, stderr_dup.0];
            const PROC_THREAD_ATTRIBUTE_HANDLE_LIST: usize = 0x0002_0002;
            if UpdateProcThreadAttribute(
                attribute_ptr,
                0,
                PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                inherited_handles.as_ptr() as *mut std::ffi::c_void,
                std::mem::size_of_val(&inherited_handles),
                null_mut(),
                null_mut(),
            ) == 0
            {
                return Err(last_error("UpdateProcThreadAttribute(HANDLE_LIST)"));
            }
            startup.lpAttributeList = attribute_ptr;

            let mut command = Vec::<u16>::new();
            command.extend(quote_arg(OsStr::new(executable)).encode_utf16());
            for arg in args {
                command.push(b' ' as u16);
                command.extend(quote_arg(OsStr::new(arg)).encode_utf16());
            }
            command.push(0);
            let application = wide(OsStr::new(executable));
            let current_dir = wide(root.as_os_str());
            let mut info: windows_sys::Win32::System::Threading::PROCESS_INFORMATION = zeroed();

            let created = CreateProcessW(
                application.as_ptr(),
                command.as_mut_ptr(),
                null(),
                null(),
                1,
                CREATE_SUSPENDED | CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT,
                null(),
                current_dir.as_ptr(),
                &startup as *const STARTUPINFOEXW as *const STARTUPINFOW,
                &mut info,
            );
            drop(attribute_guard);
            if created == 0 {
                return Err(last_error("CreateProcessW(CREATE_SUSPENDED)"));
            }

            // The process is still suspended: no Python code can run or create descendants yet.
            if let Err(error) = job.assign_and_verify(info.hProcess) {
                let _ = TerminateProcess(info.hProcess, 1);
                let _ = WaitForSingleObject(info.hProcess, INFINITE);
                CloseHandle(info.hThread);
                CloseHandle(info.hProcess);
                return Err(format!(
                    "Python was not resumed because Job Object assignment failed: {error}"
                ));
            }

            if ResumeThread(info.hThread) == u32::MAX {
                let error = last_error("ResumeThread");
                let _ = TerminateProcess(info.hProcess, 1);
                let _ = WaitForSingleObject(info.hProcess, INFINITE);
                CloseHandle(info.hThread);
                CloseHandle(info.hProcess);
                return Err(error);
            }
            CloseHandle(info.hThread);

            // Parent must close the child's read end; only the write end remains for shutdown.
            drop(stdin_child_guard);
            let parent_stdin = stdin_parent_guard.map(|h| {
                let raw = h.0;
                std::mem::forget(h);
                File::from_raw_handle(raw as _)
            });
            Ok((
                NativeChild {
                    process: info.hProcess,
                },
                parent_stdin,
            ))
        }
    }
}

/// Owns only the exact child processes spawned by this Atlas desktop instance.
///
/// The child registry uses a short-lived std mutex so shutdown never needs to
/// `try_lock()` a Tokio mutex that may be held across an HTTP readiness wait.
/// Startup itself is serialized separately with an async mutex.
enum OwnedProcess {
    Rust(Child),
    #[cfg(windows)]
    Windows(windows_job::NativeChild),
}

struct OwnedChild {
    process: OwnedProcess,
    shutdown_stdin: Option<Box<dyn Write + Send>>,
}

pub struct OwnedChildren {
    children: Mutex<Vec<OwnedChild>>,
    start_lock: AsyncMutex<()>,
    stop_requested: AtomicBool,
    started: AtomicBool,
    #[cfg(windows)]
    python_job: Mutex<Option<windows_job::Job>>,
    #[cfg(windows)]
    swap_job: Mutex<Option<windows_job::Job>>,
}

impl Default for OwnedChildren {
    fn default() -> Self {
        Self {
            children: Mutex::new(Vec::new()),
            start_lock: AsyncMutex::new(()),
            stop_requested: AtomicBool::new(false),
            started: AtomicBool::new(false),
            #[cfg(windows)]
            python_job: Mutex::new(None),
            #[cfg(windows)]
            swap_job: Mutex::new(None),
        }
    }
}

/// Resolve the Atlas runtime root without depending on the process working directory.
/// Development can override this with ATLAS_PROJECT_ROOT. Packaged builds search
/// beside the executable and its parents for the backend marker files.
pub fn project_root() -> PathBuf {
    if let Some(root) = std::env::var_os("ATLAS_RUNTIME_ROOT").map(PathBuf::from) {
        return root;
    }
    #[cfg(debug_assertions)]
    if let Some(root) = std::env::var_os("ATLAS_PROJECT_ROOT").map(PathBuf::from) {
        return root;
    }
    if let Ok(exe) = std::env::current_exe() {
        for parent in exe.ancestors() {
            let candidate = parent.join("resources").join("atlas");
            if candidate.join("server.py").is_file() {
                return candidate;
            }
        }
    }
    panic!("Atlas runtime root was not initialized by the Tauri application setup.");
}

fn data_root(root: &Path) -> PathBuf {
    std::env::var_os("ATLAS_DATA_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join(".atlas-data"))
}

/// Pick the llama-swap config. The bundled one is kept when every model file it names exists.
/// Otherwise model_discovery.py writes a config from the .gguf files found on this PC
/// (ATLAS_MODELS_DIR, the data folder, next to the install). Any failure keeps the bundled config.
fn discover_llama_config(root: &Path, bundled: &Path) -> PathBuf {
    let python = root.join("runtime").join("python").join("python.exe");
    let script = root.join("model_discovery.py");
    if !python.is_file() || !script.is_file() {
        return bundled.to_path_buf();
    }
    let mut command = Command::new(&python);
    command
        .arg(&script)
        .arg("--runtime")
        .arg(root)
        .arg("--data")
        .arg(data_root(root))
        .arg("--config")
        .arg(bundled)
        .stdin(Stdio::null());
    hide_console_window(&mut command);
    let output = match command.output() {
        Ok(o) if o.status.success() => o,
        _ => return bundled.to_path_buf(),
    };
    let parsed: Value = match serde_json::from_slice(&output.stdout) {
        Ok(v) => v,
        Err(_) => return bundled.to_path_buf(),
    };
    match parsed.get("config").and_then(Value::as_str) {
        Some(path) if !path.is_empty() && Path::new(path).is_file() => PathBuf::from(path),
        _ => bundled.to_path_buf(),
    }
}

/// Absolute settings paths remain supported for existing installs. Relative paths
/// are resolved from the Atlas root, making runtime relocation portable.
fn resolve_root_path(root: &Path, configured: &str) -> PathBuf {
    let path = PathBuf::from(configured);
    if path.is_absolute() {
        path
    } else {
        root.join(path)
    }
}

/// Release builds use only the Python interpreter packaged with Atlas.
/// PATH discovery remains available exclusively to development builds.
fn bundled_python(root: &Path) -> Option<PathBuf> {
    let candidates = [
        root.join("runtime").join("python").join("python.exe"),
        root.join("runtime").join("python").join("python"),
        root.join("runtime")
            .join("python312-test")
            .join("Scripts")
            .join("python.exe"),
    ];
    candidates.into_iter().find(|path| path.is_file())
}

fn port_ready(port: u16) -> bool {
    let address = format!("127.0.0.1:{port}");
    address
        .parse()
        .ok()
        .and_then(|addr| {
            std::net::TcpStream::connect_timeout(&addr, Duration::from_millis(250)).ok()
        })
        .is_some()
}

/// Kills a child and everything it started. On Windows `Child::kill` only ends the
/// one process, which would leave llama-swap's llama-server model processes running
/// and holding VRAM, so the whole tree is ended with taskkill first.
fn kill_process_tree(child: &mut Child) {
    #[cfg(windows)]
    {
        let mut taskkill = Command::new("taskkill");
        taskkill
            .args(["/PID", &child.id().to_string(), "/T", "/F"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        hide_console_window(&mut taskkill);
        let _ = taskkill.status();
    }
    let _ = child.kill();
    let _ = child.wait();
}

/// True when something on `url` answers like llama-swap: any success, or 401/403 when the
/// operator has enabled `apiKeys` (an auth challenge still proves a real HTTP service).
async fn wait_upstream_present(
    url: &str,
    seconds: u64,
    stop_requested: &AtomicBool,
) -> Result<(), String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| e.to_string())?;
    let until = Instant::now() + Duration::from_secs(seconds);
    loop {
        ensure_not_stopping(stop_requested)?;
        if let Ok(response) = client.get(url).send().await {
            let code = response.status().as_u16();
            if response.status().is_success() || code == 401 || code == 403 {
                return Ok(());
            }
        }
        if Instant::now() >= until {
            return Err(format!("Service did not answer: {url}"));
        }
        sleep(Duration::from_millis(300)).await;
    }
}

fn ensure_not_stopping(stop_requested: &AtomicBool) -> Result<(), String> {
    if stop_requested.load(Ordering::Acquire) {
        Err("Atlas startup was cancelled because shutdown was requested.".into())
    } else {
        Ok(())
    }
}

async fn wait_http(
    url: &str,
    seconds: u64,
    stop_requested: &AtomicBool,
    exited: &(dyn Fn() -> Option<String> + Send + Sync),
    accept_auth_challenge: bool,
) -> Result<(), String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| e.to_string())?;
    let until = Instant::now() + Duration::from_secs(seconds);

    loop {
        ensure_not_stopping(stop_requested)?;
        // Fail fast when the process we are waiting for has already died (bad config, port clash).
        if let Some(status) = exited() {
            return Err(format!(
                "Service exited before it became ready ({status}): {url}"
            ));
        }
        if let Ok(response) = client.get(url).send().await {
            let code = response.status().as_u16();
            // llama-swap with `apiKeys` enabled answers 401/403 until a key is sent;
            // that still proves it is up.
            if response.status().is_success()
                || (accept_auth_challenge && (code == 401 || code == 403))
            {
                return ensure_not_stopping(stop_requested);
            }
        }
        if Instant::now() >= until {
            return Err(format!("Service did not become ready: {url}"));
        }
        sleep(Duration::from_millis(300)).await;
    }
}

fn log_file(root: &Path, name: &str) -> Result<File, String> {
    let logs = data_root(root).join("logs");
    std::fs::create_dir_all(&logs).map_err(|e| e.to_string())?;
    // Keep one rotated copy so logs cannot grow without limit (10 MB per file).
    let path = logs.join(name);
    if std::fs::metadata(&path)
        .map(|m| m.len() > 10 * 1024 * 1024)
        .unwrap_or(false)
    {
        let rotated = logs.join(format!("{name}.1"));
        let _ = std::fs::remove_file(&rotated);
        let _ = std::fs::rename(&path, &rotated);
    }
    OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|e| e.to_string())
}

// Windows: prevent console-subsystem child processes from opening a visible console.
fn hide_console_window(command: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
}

#[cfg(not(windows))]
fn spawn_python(root: &Path, script: &Path) -> Result<OwnedProcess, String> {
    let stdout = log_file(root, "atlas-server.log")?;
    let stderr = stdout.try_clone().map_err(|e| e.to_string())?;
    let candidates: Vec<(&str, Vec<String>)> = vec![
        ("python3", vec![script.display().to_string()]),
        ("python", vec![script.display().to_string()]),
    ];
    let mut last = String::new();
    for (exe, args) in candidates {
        let mut command = Command::new(exe);
        command
            .args(args)
            .current_dir(root)
            .stdin(Stdio::null())
            .stdout(Stdio::from(stdout.try_clone().map_err(|e| e.to_string())?))
            .stderr(Stdio::from(stderr.try_clone().map_err(|e| e.to_string())?));
        match command.spawn() {
            Ok(child) => return Ok(OwnedProcess::Rust(child)),
            Err(error) => last = format!("{exe}: {error}"),
        }
    }
    Err(format!("Could not start Python server. Install Python 3 and ensure python3 or python is on PATH. {last}"))
}

#[cfg(windows)]
fn resolve_python_executable(name: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    for directory in std::env::split_paths(&path) {
        for candidate_name in [format!("{name}.exe"), name.to_owned()] {
            let candidate = directory.join(candidate_name);
            if candidate.is_file() {
                return Some(candidate.canonicalize().unwrap_or(candidate));
            }
        }
    }
    None
}

#[cfg(windows)]
fn spawn_python(
    root: &Path,
    script: &Path,
    job: &windows_job::Job,
) -> Result<OwnedProcess, String> {
    let stdout = log_file(root, "atlas-server.log")?;
    let stderr = stdout.try_clone().map_err(|e| e.to_string())?;
    if let Some(executable) = bundled_python(root) {
        let executable = executable.to_string_lossy().into_owned();
        let args = vec![script.display().to_string()];
        let (child, _) =
            windows_job::spawn_python(&executable, &args, root, &stdout, &stderr, false, job)?;
        return Ok(OwnedProcess::Windows(child));
    }
    #[cfg(debug_assertions)]
    {
        let candidates: Vec<(&str, Vec<String>)> = vec![
            ("py", vec!["-3".into(), script.display().to_string()]),
            ("python", vec![script.display().to_string()]),
        ];
        let mut last = String::new();
        for (exe, args) in candidates {
            let Some(executable) = resolve_python_executable(exe) else {
                last = format!("{exe}.exe was not found in PATH");
                continue;
            };
            let executable = executable.to_string_lossy().into_owned();
            match windows_job::spawn_python(&executable, &args, root, &stdout, &stderr, false, job)
            {
                Ok((child, _)) => return Ok(OwnedProcess::Windows(child)),
                Err(error) if error.contains("CreateProcessW") => last = format!("{exe}: {error}"),
                Err(error) => return Err(error),
            }
        }
        return Err(format!("Could not start development Python server: {last}"));
    }
    #[cfg(not(debug_assertions))]
    Err(format!(
        "Packaged Python interpreter missing: {}",
        root.join("runtime")
            .join("python")
            .join("python.exe")
            .display()
    ))
}

#[cfg(not(windows))]
fn spawn_programming_worker(
    root: &Path,
    script: &Path,
    api: u16,
) -> Result<(OwnedProcess, Box<dyn Write + Send>), String> {
    let stdout = log_file(root, "atlas-programming-worker.log")?;
    let stderr = stdout.try_clone().map_err(|e| e.to_string())?;
    let candidates: Vec<(&str, Vec<String>)> = vec![
        (
            "python3",
            vec![
                script.display().to_string(),
                "--server".into(),
                format!("http://127.0.0.1:{api}"),
            ],
        ),
        (
            "python",
            vec![
                script.display().to_string(),
                "--server".into(),
                format!("http://127.0.0.1:{api}"),
            ],
        ),
    ];
    let mut last = String::new();
    for (exe, args) in candidates {
        let mut command = Command::new(exe);
        command
            .args(args)
            .current_dir(root)
            .stdin(Stdio::piped())
            .stdout(Stdio::from(stdout.try_clone().map_err(|e| e.to_string())?))
            .stderr(Stdio::from(stderr.try_clone().map_err(|e| e.to_string())?));
        match command.spawn() {
            Ok(mut child) => match child.stdin.take() {
                Some(stdin) => return Ok((OwnedProcess::Rust(child), Box::new(stdin))),
                None => {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err("Programming worker stdin pipe was unavailable".into());
                }
            },
            Err(error) => last = format!("{exe}: {error}"),
        }
    }
    Err(format!("Could not start programming worker: {last}"))
}

#[cfg(windows)]
fn spawn_programming_worker(
    root: &Path,
    script: &Path,
    api: u16,
    job: &windows_job::Job,
) -> Result<(OwnedProcess, Box<dyn Write + Send>), String> {
    let stdout = log_file(root, "atlas-programming-worker.log")?;
    let stderr = stdout.try_clone().map_err(|e| e.to_string())?;
    if let Some(executable) = bundled_python(root) {
        let executable = executable.to_string_lossy().into_owned();
        let args = vec![
            script.display().to_string(),
            "--server".into(),
            format!("http://127.0.0.1:{api}"),
        ];
        let (child, stdin) =
            windows_job::spawn_python(&executable, &args, root, &stdout, &stderr, true, job)?;
        return Ok((
            OwnedProcess::Windows(child),
            Box::new(stdin.ok_or("Programming worker stdin pipe was not created")?),
        ));
    }
    #[cfg(debug_assertions)]
    {
        let candidates: Vec<(&str, Vec<String>)> = vec![
            (
                "py",
                vec![
                    "-3".into(),
                    script.display().to_string(),
                    "--server".into(),
                    format!("http://127.0.0.1:{api}"),
                ],
            ),
            (
                "python",
                vec![
                    script.display().to_string(),
                    "--server".into(),
                    format!("http://127.0.0.1:{api}"),
                ],
            ),
        ];
        let mut last = String::new();
        for (exe, args) in candidates {
            let Some(executable) = resolve_python_executable(exe) else {
                last = format!("{exe}.exe was not found in PATH");
                continue;
            };
            let executable = executable.to_string_lossy().into_owned();
            match windows_job::spawn_python(&executable, &args, root, &stdout, &stderr, true, job) {
                Ok((child, Some(stdin))) => {
                    return Ok((OwnedProcess::Windows(child), Box::new(stdin)))
                }
                Ok((_child, None)) => {
                    return Err("Programming worker stdin pipe was not created".into())
                }
                Err(error) if error.contains("CreateProcessW") => last = format!("{exe}: {error}"),
                Err(error) => return Err(error),
            }
        }
        return Err(format!(
            "Could not start development programming worker: {last}"
        ));
    }
    #[cfg(not(debug_assertions))]
    Err(format!(
        "Packaged Python interpreter missing: {}",
        root.join("runtime")
            .join("python")
            .join("python.exe")
            .display()
    ))
}

async fn has_fresh_programming_worker(client: &reqwest::Client, api: u16) -> Result<bool, String> {
    let response = client
        .get(format!("http://127.0.0.1:{api}/api/ops/agents"))
        .send()
        .await
        .map_err(|e| format!("Cannot inspect existing workers: {e}"))?;

    if !response.status().is_success() {
        return Err(format!("Agent listing returned HTTP {}", response.status()));
    }

    let data: Value = response.json().await.map_err(|e| e.to_string())?;
    let agents = data
        .get("agents")
        .and_then(Value::as_array)
        .ok_or("Agent listing did not contain an agents array")?;

    for agent in agents {
        let name = agent.get("name").and_then(Value::as_str).unwrap_or("");
        let metadata = agent.get("metadata");
        let worker_type = metadata
            .and_then(|m| m.get("worker_type"))
            .and_then(Value::as_str)
            .unwrap_or("");

        let is_programmer = name == "atlas-programming-worker" || worker_type == "programming";

        let status = agent.get("status").and_then(Value::as_str).unwrap_or("");
        let age = agent
            .get("heartbeat_age_seconds")
            .and_then(Value::as_f64)
            .unwrap_or(f64::MAX);

        if is_programmer && (status == "online" || status == "busy") && age <= 30.0 {
            return Ok(true);
        }
    }

    Ok(false)
}

async fn wait_for_programming_worker(
    client: &reqwest::Client,
    api: u16,
    stop_requested: &AtomicBool,
) -> Result<(), String> {
    let until = Instant::now() + Duration::from_secs(20);

    loop {
        ensure_not_stopping(stop_requested)?;

        if has_fresh_programming_worker(client, api).await? {
            return Ok(());
        }

        if Instant::now() >= until {
            return Err("Programming worker did not register within 20 seconds".into());
        }

        sleep(Duration::from_millis(500)).await;
    }
}

impl OwnedChildren {
    /// Exit status text if the Rust-owned child at `index` has already ended.
    fn rust_child_exit(&self, index: usize) -> Option<String> {
        let mut children = self
            .children
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        match children.get_mut(index).map(|owned| &mut owned.process) {
            Some(OwnedProcess::Rust(child)) => match child.try_wait() {
                Ok(Some(status)) => Some(status.to_string()),
                _ => None,
            },
            _ => None,
        }
    }

    fn register(
        &self,
        mut process: OwnedProcess,
        shutdown_stdin: Option<Box<dyn Write + Send>>,
    ) -> Result<(), String> {
        let mut children = self
            .children
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if self.stop_requested.load(Ordering::Acquire) {
            match &mut process {
                OwnedProcess::Rust(child) => {
                    let _ = child.kill();
                    let _ = child.wait();
                }
                #[cfg(windows)]
                OwnedProcess::Windows(child) => child.terminate_and_wait(),
            }
            return Err("Atlas shutdown was requested while a child process was starting; the new process was terminated.".into());
        }
        children.push(OwnedChild {
            process,
            shutdown_stdin,
        });
        Ok(())
    }

    #[cfg(windows)]
    fn with_python_job<T>(
        &self,
        f: impl FnOnce(&windows_job::Job) -> Result<T, String>,
    ) -> Result<T, String> {
        let mut slot = self
            .python_job
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if self.stop_requested.load(Ordering::Acquire) {
            return Err("Atlas shutdown was requested before Python process creation.".into());
        }
        if slot.is_none() {
            *slot = Some(windows_job::Job::create()?);
        }
        f(slot.as_ref().expect("Job Object initialized"))
    }

    /// Serializes startup and rolls back every child started by this attempt if
    /// any later prerequisite, readiness check, or identity check fails.
    pub async fn start(&self) -> Result<String, String> {
        let _start_guard = self.start_lock.lock().await;

        // Startup can be requested by React lifecycle effects, the retry button,
        // or a future recovery path. Treat it as idempotent for this desktop
        // instance: never spawn another server after a successful start.
        if self.started.load(Ordering::Acquire) {
            return Ok("Atlas services are already running under this desktop instance.".into());
        }

        self.stop_requested.store(false, Ordering::Release);
        let result = self.start_inner().await;
        match result {
            Ok(message) if !self.stop_requested.load(Ordering::Acquire) => {
                self.started.store(true, Ordering::Release);
                Ok(message)
            }
            Ok(_) => {
                self.stop();
                Err("Atlas startup was cancelled because shutdown was requested.".into())
            }
            Err(error) => {
                // Startup failure must not leave llama-swap or the API orphaned.
                self.stop();
                Err(error)
            }
        }
    }

    async fn start_inner(&self) -> Result<String, String> {
        let root = project_root();
        let settings_path = data_root(&root).join("settings.json");
        let settings: Value = serde_json::from_slice(
            &tokio::fs::read(&settings_path)
                .await
                .map_err(|e| format!("Cannot read {}: {e}", settings_path.display()))?,
        )
        .map_err(|e| format!("Invalid settings.json: {e}"))?;

        let upstream = settings
            .get("upstream_port")
            .and_then(Value::as_u64)
            .unwrap_or(8080) as u16;
        let api = settings
            .get("server_port")
            .and_then(Value::as_u64)
            .unwrap_or(8090) as u16;

        ensure_not_stopping(&self.stop_requested)?;

        if port_ready(upstream) {
            // Something already listens here. Reuse it only if it behaves like llama-swap;
            // otherwise Ops would stay blank with no explanation.
            wait_upstream_present(
                &format!("http://127.0.0.1:{upstream}/v1/models"),
                8,
                &self.stop_requested,
            )
            .await
            .map_err(|_| {
                format!(
                    "Port {upstream} is in use by a service that does not answer /v1/models like llama-swap. Close that program or change upstream_port in settings.json."
                )
            })?;
        } else {
            let bundled_exe = root
                .join("runtime")
                .join("llama-swap")
                .join("llama-swap.exe");
            let exe_path = if bundled_exe.is_file() {
                bundled_exe
            } else {
                #[cfg(debug_assertions)]
                {
                    let configured_exe = settings
                        .get("llama_swap_exe")
                        .and_then(Value::as_str)
                        .ok_or("settings.json missing llama_swap_exe")?;
                    resolve_root_path(&root, configured_exe)
                }
                #[cfg(not(debug_assertions))]
                {
                    return Err(format!(
                        "Packaged llama-swap executable is missing: {}",
                        bundled_exe.display()
                    ));
                }
            };
            let config_path = {
                let bundled = root.join("runtime").join("llama-swap").join("config.yaml");
                if bundled.is_file() {
                    discover_llama_config(&root, &bundled)
                } else {
                    #[cfg(debug_assertions)]
                    {
                        let configured_config = settings
                            .get("llama_swap_config")
                            .and_then(Value::as_str)
                            .ok_or("settings.json missing llama_swap_config")?;
                        resolve_root_path(&root, configured_config)
                    }
                    #[cfg(not(debug_assertions))]
                    {
                        return Err(format!(
                            "Packaged llama-swap config is missing: {}",
                            bundled.display()
                        ));
                    }
                }
            };
            if !exe_path.is_file() {
                return Err(format!(
                    "llama-swap executable not found: {}",
                    exe_path.display()
                ));
            }
            if !config_path.is_file() {
                return Err(format!(
                    "llama-swap config not found: {}",
                    config_path.display()
                ));
            }

            let exe = exe_path.to_string_lossy().into_owned();
            let config = config_path.to_string_lossy().into_owned();
            let stdout = log_file(&root, "llama-swap.log")?;
            let stderr = stdout.try_clone().map_err(|e| e.to_string())?;
            let mut command = Command::new(&exe);
            command
                .arg("--config")
                .arg(config)
                .arg("--listen")
                .arg(format!("127.0.0.1:{upstream}"))
                .current_dir(exe_path.parent().unwrap_or(&root))
                .stdin(Stdio::null())
                .stdout(Stdio::from(stdout))
                .stderr(Stdio::from(stderr));
            hide_console_window(&mut command);
            let child = command
                .spawn()
                .map_err(|e| format!("Could not start llama-swap: {e}"))?;
            // Windows: put llama-swap (and the llama-server processes it launches) in a
            // kill-on-close Job Object so they die with Atlas even after a crash or force-kill.
            // Failure here is not fatal; stop() still ends the whole tree with taskkill.
            #[cfg(windows)]
            {
                let mut slot = self
                    .swap_job
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                if slot.is_none() {
                    match windows_job::Job::create() {
                        Ok(job) => *slot = Some(job),
                        Err(e) => eprintln!("llama-swap Job Object unavailable: {e}"),
                    }
                }
                if let Some(job) = slot.as_ref() {
                    if let Err(e) = job.assign_child(&child) {
                        eprintln!("llama-swap Job Object assignment failed: {e}");
                    }
                }
            }
            let swap_index = self
                .children
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .len();
            self.register(OwnedProcess::Rust(child), None)?;
            wait_http(
                &format!("http://127.0.0.1:{upstream}/v1/models"),
                60,
                &self.stop_requested,
                &|| self.rust_child_exit(swap_index),
                true,
            )
            .await
            .map_err(|e| format!("{e}. See logs\\llama-swap.log in the Atlas data folder."))?;
        }

        ensure_not_stopping(&self.stop_requested)?;

        if !port_ready(api) {
            let script = root.join("server.py");
            if !script.is_file() {
                return Err(format!("Atlas server.py missing: {}", script.display()));
            }
            #[cfg(windows)]
            {
                let process = self.with_python_job(|job| spawn_python(&root, &script, job))?;
                self.register(process, None)?;
            }
            #[cfg(not(windows))]
            self.register(spawn_python(&root, &script)?, None)?;
            wait_http(
                &format!("http://127.0.0.1:{api}/api/health"),
                20,
                &self.stop_requested,
                &|| None,
                false,
            )
            .await?;
        }

        ensure_not_stopping(&self.stop_requested)?;

        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(3))
            .build()
            .map_err(|e| e.to_string())?;
        let health = client
            .get(format!("http://127.0.0.1:{api}/api/health"))
            .send()
            .await
            .map_err(|e| format!("Atlas API health check failed on port {api}: {e}"))?;
        if !health.status().is_success() {
            return Err(format!(
                "Port {api} is occupied by a service that did not pass Atlas health verification"
            ));
        }
        let identity: Value = health
            .json()
            .await
            .map_err(|e| format!("Atlas health response was not valid JSON: {e}"))?;
        if identity.get("server_port").and_then(Value::as_u64) != Some(api as u64)
            || identity.get("upstream_port").and_then(Value::as_u64) != Some(upstream as u64)
        {
            return Err(format!(
                "Port {api} is occupied by an Atlas API with unexpected configuration; expected server {api} and upstream {upstream}."
            ));
        }

        ensure_not_stopping(&self.stop_requested)?;

        if !has_fresh_programming_worker(&client, api).await? {
            let script = root.join("agents").join("atlas_programming_worker.py");
            if !script.is_file() {
                return Err(format!("Programming worker missing: {}", script.display()));
            }

            #[cfg(windows)]
            {
                let (process, stdin) =
                    self.with_python_job(|job| spawn_programming_worker(&root, &script, api, job))?;
                self.register(process, Some(stdin))?;
            }
            #[cfg(not(windows))]
            {
                let (process, stdin) = spawn_programming_worker(&root, &script, api)?;
                self.register(process, Some(stdin))?;
            }

            wait_for_programming_worker(&client, api, &self.stop_requested).await?;
        }

        ensure_not_stopping(&self.stop_requested)?;

        Ok(format!(
            "Atlas services ready. API :{api}; llama-swap :{upstream}; programming worker online. Python processes started by this desktop instance were created suspended, assigned to and verified in its private Windows Job Object before resume; Llama-Swap, when started by this instance, is stopped with its whole process tree on exit."
        ))
    }

    /// Stops only processes retained in this instance's child registry.
    /// This is synchronous and does not silently skip shutdown because another
    /// async startup task happens to hold a Tokio mutex.
    pub fn stop(&self) {
        self.stop_requested.store(true, Ordering::Release);
        self.started.store(false, Ordering::Release);

        let mut children = self
            .children
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);

        // Give only the programming worker its documented stdin shutdown command.
        for owned in children.iter_mut().rev() {
            if let Some(mut stdin) = owned.shutdown_stdin.take() {
                let graceful = stdin
                    .write_all(b"atlas_worker_shutdown\n")
                    .and_then(|_| stdin.flush())
                    .is_ok();
                drop(stdin);
                if graceful {
                    let deadline = std::time::Instant::now() + Duration::from_secs(5);
                    loop {
                        let exited = match &mut owned.process {
                            OwnedProcess::Rust(child) => matches!(child.try_wait(), Ok(Some(_))),
                            #[cfg(windows)]
                            OwnedProcess::Windows(child) => child.has_exited().unwrap_or(false),
                        };
                        if exited || std::time::Instant::now() >= deadline {
                            break;
                        }
                        std::thread::sleep(Duration::from_millis(100));
                    }
                }
            }
        }

        // Llama-Swap is deliberately outside the Python Job Object and is stopped individually.
        for owned in children.iter_mut().rev() {
            if let OwnedProcess::Rust(child) = &mut owned.process {
                if !matches!(child.try_wait(), Ok(Some(_))) {
                    kill_process_tree(child);
                }
            }
        }

        // llama-swap's own kill-on-close Job Object (anything taskkill missed).
        #[cfg(windows)]
        {
            let mut slot = self
                .swap_job
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if let Some(job) = slot.as_ref() {
                job.terminate_all();
            }
            slot.take();
        }

        // Closing/terminating this one private Job Object affects only Python processes
        // created suspended and assigned by this supervisor, including their descendants.
        #[cfg(windows)]
        {
            let mut slot = self
                .python_job
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if let Some(job) = slot.as_ref() {
                job.terminate_all();
            }
            for owned in children.iter_mut() {
                if let OwnedProcess::Windows(child) = &mut owned.process {
                    let _ = child.wait_for(5_000);
                }
            }
            // Drop closes the kill-on-close Job Object handle after its members have been terminated.
            slot.take();
        }

        children.clear();
    }
}
