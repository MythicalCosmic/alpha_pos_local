//! The windowless Python backend (`backend\AlphaPOSBackend.exe`).

use std::fmt;
use std::fs::{self, OpenOptions};
use std::io::Read;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use alphapos_shell_core::{lifecycle, ready};
use serde_json::{json, Value};

pub const TOKEN_ENV: &str = "ALPHAPOS_CONTROL_TOKEN";
/// How long the backend may take to bind its control server.
const READY_TIMEOUT: Duration = Duration::from_secs(90);
/// Backend shutdown budget is 25 s (+ its own 32 s hard exit); kill after this.
const STOP_TIMEOUT: Duration = Duration::from_secs(35);

/// `%LOCALAPPDATA%\AlphaPOS`, derived like `desktop/config_store.py` so a
/// Startup-folder launch without LOCALAPPDATA uses the same data directory.
pub fn data_dir() -> PathBuf {
    let base = std::env::var_os("LOCALAPPDATA")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            let home = std::env::var_os("USERPROFILE")
                .or_else(|| std::env::var_os("HOME"))
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from("."));
            home.join("AppData").join("Local")
        });
    base.join("AlphaPOS")
}

pub fn backend_exe() -> PathBuf {
    if let Some(path) = std::env::var_os("ALPHAPOS_BACKEND_EXE") {
        return PathBuf::from(path);
    }
    std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|dir| dir.join("backend").join("AlphaPOSBackend.exe")))
        .unwrap_or_default()
}

fn new_token() -> String {
    let mut bytes = [0u8; 32];
    getrandom::getrandom(&mut bytes).expect("OS random source unavailable");
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

pub fn error_value(code: &str, message: &str) -> Value {
    json!({ "ok": false, "code": code, "error": message })
}

#[derive(Debug)]
pub enum StartError {
    Io(std::io::Error),
    Spawn(std::io::Error),
    ExitedEarly(Option<i32>),
    ReadyTimeout,
}

impl fmt::Display for StartError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            StartError::Io(e) => write!(f, "could not prepare the data folder: {e}"),
            StartError::Spawn(e) => write!(f, "could not start the POS backend: {e}"),
            StartError::ExitedEarly(Some(code)) => write!(f, "the POS backend exited during startup (code {code})"),
            StartError::ExitedEarly(None) => write!(f, "the POS backend exited during startup"),
            StartError::ReadyTimeout => write!(f, "the POS backend did not report ready in time"),
        }
    }
}

pub struct Backend {
    child: Child,
    port: u16,
    token: String,
    #[cfg(windows)]
    job: crate::job::Job,
}

impl Backend {
    pub fn spawn() -> Result<Backend, StartError> {
        let data = data_dir();
        let run_dir = data.join("run");
        let logs = data.join("logs");
        fs::create_dir_all(&run_dir).map_err(StartError::Io)?;
        fs::create_dir_all(&logs).map_err(StartError::Io)?;

        let ready_path = run_dir.join(format!("backend-{}.json", std::process::id()));
        let _ = fs::remove_file(&ready_path);
        let console = OpenOptions::new()
            .create(true)
            .append(true)
            .open(logs.join("backend-console.log"))
            .map_err(StartError::Io)?;
        let console_err = console.try_clone().map_err(StartError::Io)?;

        let token = new_token();
        let mut command = Command::new(backend_exe());
        command
            .arg("--parent-pid")
            .arg(std::process::id().to_string())
            .arg("--ready-file")
            .arg(&ready_path)
            .env(TOKEN_ENV, &token)
            // Never let a child keep the install directory open as its cwd.
            .current_dir(&data)
            .stdin(Stdio::null())
            .stdout(Stdio::from(console))
            .stderr(Stdio::from(console_err));

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            command.creation_flags(CREATE_NO_WINDOW);
        }

        #[cfg(windows)]
        let job = crate::job::Job::kill_on_close().map_err(StartError::Io)?;
        let mut child = command.spawn().map_err(StartError::Spawn)?;
        #[cfg(windows)]
        if let Err(error) = job.assign(&child) {
            let _ = child.kill();
            let _ = child.wait();
            return Err(StartError::Io(error));
        }

        let deadline = Instant::now() + READY_TIMEOUT;
        let port = loop {
            if let Some(status) = child.try_wait().map_err(StartError::Io)? {
                return Err(StartError::ExitedEarly(status.code()));
            }
            if let Ok(bytes) = fs::read(&ready_path) {
                if let Ok(ready) = ready::parse(&bytes, Some(child.id())) {
                    break ready.port;
                }
            }
            if Instant::now() >= deadline {
                let _ = child.kill();
                let _ = child.wait();
                return Err(StartError::ReadyTimeout);
            }
            std::thread::sleep(Duration::from_millis(100));
        };
        let _ = fs::remove_file(&ready_path);

        Ok(Backend {
            child,
            port,
            token,
            #[cfg(windows)]
            job,
        })
    }

    pub fn url(&self) -> String {
        format!("http://127.0.0.1:{}/", self.port)
    }

    fn agent(timeout: Duration) -> ureq::Agent {
        ureq::AgentBuilder::new().timeout(timeout).build()
    }

    pub fn lifecycle(&self) -> Result<lifecycle::Snapshot, String> {
        let response = Self::agent(Duration::from_secs(3))
            .get(&format!("{}lifecycle", self.url()))
            .set("X-Control-Token", &self.token)
            .call()
            .map_err(|e| e.to_string())?;
        let mut body = Vec::new();
        response
            .into_reader()
            .take(1 << 20)
            .read_to_end(&mut body)
            .map_err(|e| e.to_string())?;
        lifecycle::parse(&body).map_err(|e| e.to_string())
    }

    /// Forward one panel call to `desktop/bridge.py:Api`.
    pub fn call(&self, method: &str, args: &[Value], timeout: Duration) -> Value {
        let body = Value::Array(args.to_vec()).to_string();
        match Self::agent(timeout)
            .post(&format!("{}api/{}", self.url(), method))
            .set("X-Control-Token", &self.token)
            .set("Content-Type", "application/json")
            .send_string(&body)
        {
            Ok(response) => response
                .into_json::<Value>()
                .unwrap_or_else(|e| error_value("backend_invalid_response", &e.to_string())),
            Err(ureq::Error::Status(403, _)) => error_value("auth", "forbidden"),
            Err(error) => error_value("backend_unavailable", &error.to_string()),
        }
    }

    /// `Some(code)` once the process has exited.
    pub fn exited(&mut self) -> Option<Option<i32>> {
        match self.child.try_wait() {
            Ok(Some(status)) => Some(status.code()),
            Ok(None) => None,
            Err(_) => Some(None),
        }
    }

    /// Ask for a bounded graceful stop, then kill the whole job. Returns true
    /// when the backend exited on its own.
    pub fn stop(mut self) -> bool {
        let _ = Self::agent(Duration::from_secs(3))
            .post(&format!("{}lifecycle/shutdown", self.url()))
            .set("X-Control-Token", &self.token)
            .send_string("");
        let deadline = Instant::now() + STOP_TIMEOUT;
        while Instant::now() < deadline {
            if let Ok(Some(_)) = self.child.try_wait() {
                return true;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        #[cfg(windows)]
        self.job.terminate();
        let _ = self.child.kill();
        let _ = self.child.wait();
        false
    }
}

/// Per-method proxy timeouts, mirroring the panel's expectations.
pub fn call_timeout(method: &str) -> Duration {
    match method {
        "run_setup" | "flush_database" | "factory_reset" => Duration::from_secs(600),
        m if m.starts_with("cloud_") || m.starts_with("check_updates") => Duration::from_secs(120),
        _ => Duration::from_secs(30),
    }
}
