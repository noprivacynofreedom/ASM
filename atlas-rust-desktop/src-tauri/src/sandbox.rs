//! The Atlas coder sandbox: a small Linux desktop in Docker that the Operations panel shows (noVNC).
//!
//! Atlas starts it when Atlas opens and stops it when Atlas closes. Only std and ring are used here
//! (no Tauri types), so the logic can be tested without the desktop libraries.
//!
//! Rules:
//! - ONE container. The name is fixed in docker/atlas-coder-sandbox/docker-compose.yml, and
//!   `docker compose up -d` reuses it. Atlas never runs `docker run`.
//! - Atlas stops only what it started. A sandbox that was already running is left running.
//! - Atlas never deletes a container. If a container with the same name exists and Compose did not make it,
//!   Atlas writes the command to the log and does nothing else.
//! - Switch it off with the environment variable ATLAS_SANDBOX_AUTOSTART=0.
use std::{
    ffi::OsString,
    fs,
    io::Write,
    path::{Path, PathBuf},
    process::{Command, Output},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

const PLACEHOLDER: &str = "change-me-first";
const PASSWORD_KEY: &str = "SANDBOX_VNC_PASSWORD";
/// Letters and digits that cannot be mistaken for each other (no 0/O, 1/l/I).
const ALPHABET: &[u8] = b"abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";

#[derive(Debug, PartialEq)]
pub enum Outcome {
    /// Atlas started it and will stop it when Atlas closes.
    Started,
    /// It was already running. Atlas leaves it running when it closes.
    AlreadyRunning,
    /// Docker is not installed, or Docker Desktop is not running yet.
    DockerNotReady(String),
    /// A container with this name exists and Compose did not make it.
    NameTaken(String),
    /// Something else uses port 6080.
    PortTaken(String),
    Failed(String),
}

pub struct Sandbox {
    docker: OsString,
    owned: AtomicBool,
}

impl Sandbox {
    pub fn new() -> Self {
        Self::with_program("docker")
    }

    #[allow(dead_code)] // used by the tests
    pub fn with_program(program: impl Into<OsString>) -> Self {
        Sandbox {
            docker: program.into(),
            owned: AtomicBool::new(false),
        }
    }

    fn run(&self, dir: &Path, args: &[&str]) -> Result<Output, String> {
        let mut command = Command::new(&self.docker);
        command.current_dir(dir).args(args);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            command.creation_flags(CREATE_NO_WINDOW);
        }
        command
            .output()
            .map_err(|e| format!("could not run docker: {e}"))
    }

    /// One try. Does not wait and does not retry.
    pub fn start(&self, dir: &Path) -> Outcome {
        match self.run(dir, &["compose", "ps", "--status", "running", "-q"]) {
            Err(e) => return Outcome::DockerNotReady(e),
            Ok(out)
                if out.status.success()
                    && !String::from_utf8_lossy(&out.stdout).trim().is_empty() =>
            {
                return Outcome::AlreadyRunning;
            }
            Ok(_) => {}
        }
        let out = match self.run(dir, &["compose", "up", "-d"]) {
            Err(e) => return Outcome::DockerNotReady(e),
            Ok(out) => out,
        };
        if out.status.success() {
            self.owned.store(true, Ordering::Release);
            return Outcome::Started;
        }
        classify_failure(&String::from_utf8_lossy(&out.stderr))
    }

    /// Tries again while Docker Desktop is still starting (common right after sign-in).
    pub fn start_with_retry(&self, dir: &Path, attempts: u32, wait: Duration) -> Outcome {
        let mut outcome = self.start(dir);
        for _ in 1..attempts {
            if !matches!(outcome, Outcome::DockerNotReady(_)) {
                break;
            }
            thread::sleep(wait);
            outcome = self.start(dir);
        }
        outcome
    }

    /// Stops the container, only if Atlas started it. Safe to call twice. Keeps the container and the workspace.
    /// Returns true when it ran `docker compose stop`.
    pub fn stop(&self, dir: &Path) -> bool {
        if !self.owned.swap(false, Ordering::AcqRel) {
            return false;
        }
        let _ = self.run(dir, &["compose", "stop", "-t", "3"]);
        true
    }

    pub fn owns_container(&self) -> bool {
        self.owned.load(Ordering::Acquire)
    }
}

/// Maps Docker's error text to one plain answer. The text is cut to its last 500 characters so a log entry stays small.
pub fn classify_failure(stderr: &str) -> Outcome {
    // Keep the END of Docker's message: for a failed build the Dockerfile lines come first and the real error last.
    let chars: Vec<char> = stderr.trim().chars().collect();
    let text: String = chars[chars.len().saturating_sub(500)..].iter().collect();
    let low = text.to_ascii_lowercase();
    if low.contains("is already in use by container")
        || low.contains("conflict. the container name")
    {
        Outcome::NameTaken(text)
    } else if low.contains("port is already allocated") || low.contains("address already in use") {
        Outcome::PortTaken(text)
    } else if low.contains("cannot connect to the docker daemon")
        || low.contains("error during connect")
        || low.contains("docker daemon is not running")
        || low.contains("failed to connect to the docker api")
        || low.contains("the system cannot find the file specified")
    {
        Outcome::DockerNotReady(text)
    } else {
        Outcome::Failed(text)
    }
}

/// Finds docker/atlas-coder-sandbox next to the install (the install is <project>\app\atlas-desktop.exe),
/// or wherever ATLAS_SANDBOX_DIR points.
pub fn find_compose_dir(exe: &Path, override_dir: Option<PathBuf>) -> Option<PathBuf> {
    let has_compose = |d: &Path| d.join("docker-compose.yml").is_file();
    if let Some(d) = override_dir {
        return if has_compose(&d) { Some(d) } else { None };
    }
    exe.ancestors()
        .map(|a| a.join("docker").join("atlas-coder-sandbox"))
        .find(|d| has_compose(d))
}

#[derive(Debug, PartialEq)]
pub enum Password {
    Missing,
    Placeholder,
    Set,
}

pub fn password_state(env_text: &str) -> Password {
    for line in env_text.lines() {
        let line = line.trim();
        if let Some(rest) = line.strip_prefix(PASSWORD_KEY) {
            if let Some(value) = rest.trim_start().strip_prefix('=') {
                let value = value.trim().trim_matches('"').trim_matches('\'');
                return if value.is_empty() || value == PLACEHOLDER {
                    Password::Placeholder
                } else {
                    Password::Set
                };
            }
        }
    }
    Password::Missing
}

pub fn with_password(env_text: &str, password: &str) -> String {
    let mut out = Vec::new();
    let mut replaced = false;
    for line in env_text.lines() {
        let t = line.trim();
        if !replaced
            && t.strip_prefix(PASSWORD_KEY)
                .map_or(false, |r| r.trim_start().starts_with('='))
        {
            out.push(format!("{PASSWORD_KEY}={password}"));
            replaced = true;
        } else {
            out.push(line.to_string());
        }
    }
    if !replaced {
        out.push(format!("{PASSWORD_KEY}={password}"));
    }
    out.join("\n") + "\n"
}

/// Eight characters: a VNC password counts only the first eight.
pub fn random_password() -> Result<String, String> {
    use ring::rand::{SecureRandom, SystemRandom};
    let mut bytes = [0u8; 8];
    SystemRandom::new()
        .fill(&mut bytes)
        .map_err(|_| "no random numbers available".to_string())?;
    Ok(bytes
        .iter()
        .map(|b| ALPHABET[*b as usize % ALPHABET.len()] as char)
        .collect())
}

/// Compose refuses to start without a password. Writes .env only when it is missing or still holds the
/// placeholder from .env.example. A password you chose is never changed. Returns the new password, if one was made.
pub fn ensure_env(dir: &Path) -> Result<Option<String>, String> {
    let path = dir.join(".env");
    let current = fs::read_to_string(&path).unwrap_or_default();
    if password_state(&current) == Password::Set {
        return Ok(None);
    }
    let password = random_password()?;
    fs::write(&path, with_password(&current, &password))
        .map_err(|e| format!("could not write {}: {e}", path.display()))?;
    Ok(Some(password))
}

fn log(path: &Path, message: &str) {
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    if let Ok(mut file) = fs::OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "[{secs}] sandbox: {message}");
    }
}

/// Where the compose folder is, for the stop call at exit.
pub fn locate() -> Option<PathBuf> {
    let override_dir = std::env::var_os("ATLAS_SANDBOX_DIR").map(PathBuf::from);
    let exe = std::env::current_exe().ok()?;
    find_compose_dir(&exe, override_dir)
}

/// Called once when Atlas opens. Returns at once: the work runs on its own thread.
pub fn autostart(sandbox: Arc<Sandbox>, log_file: PathBuf) {
    if std::env::var("ATLAS_SANDBOX_AUTOSTART")
        .map(|v| v.trim() == "0")
        .unwrap_or(false)
    {
        log(&log_file, "autostart is off (ATLAS_SANDBOX_AUTOSTART=0)");
        return;
    }
    let Some(dir) = locate() else {
        log(
            &log_file,
            "docker/atlas-coder-sandbox was not found next to this install; nothing started",
        );
        return;
    };
    thread::spawn(move || {
        match ensure_env(&dir) {
            Ok(Some(pw)) => log(
                &log_file,
                &format!(
                    "made a VNC password and saved it in {}\\.env (first 8 characters count): {pw}",
                    dir.display()
                ),
            ),
            Ok(None) => {}
            Err(e) => {
                log(&log_file, &e);
                return;
            }
        }
        let outcome = sandbox.start_with_retry(&dir, 12, Duration::from_secs(10));
        let line = match &outcome {
            Outcome::Started => "started; it will be stopped when Atlas closes. Open http://127.0.0.1:6080/ ".to_string(),
            Outcome::AlreadyRunning => "already running; Atlas leaves it running when it closes".to_string(),
            Outcome::DockerNotReady(e) => format!("Docker is not ready, gave up after 2 minutes: {e}"),
            Outcome::NameTaken(e) => format!(
                "a container named atlas-coder-sandbox-live exists and Compose did not make it. Nothing was changed. To let Atlas manage it, run: docker rm -f atlas-coder-sandbox-live  ({e})"
            ),
            Outcome::PortTaken(e) => format!("port 6080 is used by another program or container. Stop that one first: {e}"),
            Outcome::Failed(e) => format!("start failed: {e}"),
        };
        log(&log_file, &line);
    });
}

/// Called when Atlas closes.
pub fn stop_at_exit(sandbox: &Sandbox, log_file: &Path) {
    if !sandbox.owns_container() {
        return;
    }
    if let Some(dir) = locate() {
        if sandbox.stop(&dir) {
            log(log_file, "stopped (Atlas closed)");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    /// Tests that write a fake `docker` script and run it take this lock. Without it, another test thread can start a
    /// process while the script is still open for writing, and Linux answers "Text file busy".
    #[cfg(unix)]
    static SERIAL: Mutex<()> = Mutex::new(());

    fn temp_dir(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!(
            "atlas-sandbox-test-{}-{}",
            std::process::id(),
            name
        ));
        let _ = fs::remove_dir_all(&d);
        fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn password_state_reads_the_three_cases() {
        assert_eq!(password_state(""), Password::Missing);
        assert_eq!(password_state("OTHER=1\n"), Password::Missing);
        assert_eq!(
            password_state("SANDBOX_VNC_PASSWORD=change-me-first\n"),
            Password::Placeholder
        );
        assert_eq!(
            password_state("SANDBOX_VNC_PASSWORD=\n"),
            Password::Placeholder
        );
        assert_eq!(
            password_state("SANDBOX_VNC_PASSWORD=\"hunter22\"\n"),
            Password::Set
        );
        assert_eq!(
            password_state("# SANDBOX_VNC_PASSWORD=x\n"),
            Password::Missing
        );
    }

    #[test]
    fn with_password_replaces_or_adds_and_keeps_other_lines() {
        assert_eq!(
            with_password("SANDBOX_VNC_PASSWORD=change-me-first\n", "abc"),
            "SANDBOX_VNC_PASSWORD=abc\n"
        );
        assert_eq!(
            with_password("A=1\nSANDBOX_VNC_PASSWORD=x\nB=2\n", "abc"),
            "A=1\nSANDBOX_VNC_PASSWORD=abc\nB=2\n"
        );
        assert_eq!(
            with_password("A=1\n", "abc"),
            "A=1\nSANDBOX_VNC_PASSWORD=abc\n"
        );
        assert_eq!(with_password("", "abc"), "SANDBOX_VNC_PASSWORD=abc\n");
    }

    #[test]
    fn random_password_is_eight_clear_characters_and_differs() {
        let a = random_password().unwrap();
        let b = random_password().unwrap();
        assert_eq!(a.len(), 8);
        assert!(a.bytes().all(|c| ALPHABET.contains(&c)));
        assert_ne!(a, b);
    }

    #[test]
    fn ensure_env_never_changes_a_password_you_chose() {
        let d = temp_dir("env-keep");
        fs::write(d.join(".env"), "SANDBOX_VNC_PASSWORD=mine-123\nX=1\n").unwrap();
        assert_eq!(ensure_env(&d).unwrap(), None);
        assert_eq!(
            fs::read_to_string(d.join(".env")).unwrap(),
            "SANDBOX_VNC_PASSWORD=mine-123\nX=1\n"
        );
    }

    #[test]
    fn ensure_env_makes_a_password_when_missing_or_placeholder() {
        let d = temp_dir("env-make");
        let made = ensure_env(&d).unwrap().expect("no .env: should make one");
        assert_eq!(
            fs::read_to_string(d.join(".env")).unwrap(),
            format!("SANDBOX_VNC_PASSWORD={made}\n")
        );
        fs::write(d.join(".env"), "SANDBOX_VNC_PASSWORD=change-me-first\n").unwrap();
        let again = ensure_env(&d)
            .unwrap()
            .expect("placeholder: should replace");
        assert_ne!(again, "change-me-first");
        assert_eq!(ensure_env(&d).unwrap(), None); // now it is set: left alone
    }

    #[test]
    fn find_compose_dir_walks_up_from_the_exe_and_honours_the_override() {
        let root = temp_dir("find");
        let compose = root.join("docker").join("atlas-coder-sandbox");
        fs::create_dir_all(&compose).unwrap();
        fs::write(compose.join("docker-compose.yml"), "services: {}\n").unwrap();
        let exe = root.join("app").join("atlas-desktop.exe");
        assert_eq!(find_compose_dir(&exe, None), Some(compose.clone()));
        let elsewhere = temp_dir("find-elsewhere"); // a folder with no docker/atlas-coder-sandbox above it
        assert_eq!(
            find_compose_dir(&elsewhere.join("app").join("a.exe"), None),
            None
        );
        assert_eq!(
            find_compose_dir(&exe, Some(compose.clone())),
            Some(compose.clone())
        );
        assert_eq!(find_compose_dir(&exe, Some(root.join("missing"))), None);
    }

    #[test]
    fn classify_failure_names_each_cause() {
        assert!(matches!(classify_failure("Error response from daemon: Conflict. The container name \"/atlas-coder-sandbox-live\" is already in use by container \"abc\""), Outcome::NameTaken(_)));
        assert!(matches!(
            classify_failure("Bind for 127.0.0.1:6080 failed: port is already allocated"),
            Outcome::PortTaken(_)
        ));
        assert!(matches!(classify_failure("error during connect: this error may indicate that the docker daemon is not running"), Outcome::DockerNotReady(_)));
        assert!(matches!(
            classify_failure("something else"),
            Outcome::Failed(_)
        ));
        let long = format!("{}REAL-ERROR-AT-THE-END", "x".repeat(5000));
        assert!(match classify_failure(&long) {
            Outcome::Failed(t) => t.chars().count() == 500 && t.ends_with("REAL-ERROR-AT-THE-END"),
            _ => false,
        });
    }

    #[cfg(unix)]
    fn fake_docker(name: &str, ps_out: &str, up_code: i32, up_err: &str) -> (PathBuf, PathBuf) {
        use std::os::unix::fs::PermissionsExt;
        let d = temp_dir(name);
        let script = d.join("docker");
        let calls = d.join("calls.txt");
        fs::write(
            &script,
            format!(
                "#!/bin/sh\necho \"$@\" >> '{calls}'\ncase \"$*\" in\n \"compose ps --status running -q\") printf '%s' '{ps_out}';;\n \"compose up -d\") echo '{up_err}' >&2; exit {up_code};;\nesac\nexit 0\n",
                calls = calls.display()
            ),
        )
        .unwrap();
        fs::set_permissions(&script, fs::Permissions::from_mode(0o755)).unwrap();
        (script, calls)
    }

    #[cfg(unix)]
    fn calls_of(path: &Path) -> Vec<String> {
        fs::read_to_string(path)
            .unwrap_or_default()
            .lines()
            .map(String::from)
            .collect()
    }

    #[cfg(unix)]
    #[test]
    fn start_brings_it_up_once_and_stop_only_stops_what_atlas_started() {
        let _lock = SERIAL.lock().unwrap_or_else(|e| e.into_inner());
        let (script, calls) = fake_docker("start-ok", "", 0, "");
        let work = temp_dir("work-ok");
        let sb = Sandbox::with_program(script);
        assert_eq!(sb.start(&work), Outcome::Started);
        assert!(sb.owns_container());
        assert!(sb.stop(&work));
        assert!(!sb.stop(&work)); // second call does nothing
        assert_eq!(
            calls_of(&calls),
            vec![
                "compose ps --status running -q",
                "compose up -d",
                "compose stop -t 3"
            ]
        );
    }

    #[cfg(unix)]
    #[test]
    fn already_running_is_left_alone_and_never_stopped() {
        let _lock = SERIAL.lock().unwrap_or_else(|e| e.into_inner());
        let (script, calls) = fake_docker("start-running", "abc123", 0, "");
        let work = temp_dir("work-running");
        let sb = Sandbox::with_program(script);
        assert_eq!(sb.start(&work), Outcome::AlreadyRunning);
        assert!(!sb.owns_container());
        assert!(!sb.stop(&work));
        assert_eq!(calls_of(&calls), vec!["compose ps --status running -q"]); // no "up", no "stop"
    }

    #[cfg(unix)]
    #[test]
    fn a_name_clash_changes_nothing_and_is_not_owned() {
        let _lock = SERIAL.lock().unwrap_or_else(|e| e.into_inner());
        let (script, calls) = fake_docker(
            "start-clash",
            "",
            1,
            "Conflict. The container name is already in use by container x",
        );
        let work = temp_dir("work-clash");
        let sb = Sandbox::with_program(script);
        assert!(matches!(sb.start(&work), Outcome::NameTaken(_)));
        assert!(!sb.stop(&work));
        assert!(calls_of(&calls)
            .iter()
            .all(|c| !c.contains("rm") && !c.contains("stop")));
    }

    #[cfg(unix)]
    #[test]
    fn retry_waits_for_docker_and_then_starts() {
        let _lock = SERIAL.lock().unwrap_or_else(|e| e.into_inner());
        use std::os::unix::fs::PermissionsExt;
        let d = temp_dir("retry");
        let state = d.join("n");
        let script = d.join("docker");
        // "up" fails with a daemon error the first two times, then works.
        fs::write(
            &script,
            format!(
                "#!/bin/sh\ncase \"$*\" in\n \"compose ps --status running -q\") exit 0;;\n \"compose up -d\") n=$(cat '{s}' 2>/dev/null || echo 0); n=$((n+1)); echo $n > '{s}'; if [ $n -lt 3 ]; then echo 'error during connect: docker daemon is not running' >&2; exit 1; fi; exit 0;;\nesac\nexit 0\n",
                s = state.display()
            ),
        )
        .unwrap();
        fs::set_permissions(&script, fs::Permissions::from_mode(0o755)).unwrap();
        let work = temp_dir("work-retry");
        let sb = Sandbox::with_program(script);
        assert_eq!(
            sb.start_with_retry(&work, 5, Duration::from_millis(1)),
            Outcome::Started
        );
        // Out of tries: still the daemon error, and it is not owned.
        let sb2 = Sandbox::with_program(d.join("missing-docker"));
        assert!(matches!(
            sb2.start_with_retry(&work, 2, Duration::from_millis(1)),
            Outcome::DockerNotReady(_)
        ));
    }
}
