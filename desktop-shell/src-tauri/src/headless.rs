//! Windowless verification modes used by CI and support.
//!
//!   AlphaPOS.exe --headless-smoke       start backend, wait for serving, check the
//!                                       POS server, stop gracefully, exit 0
//!   AlphaPOS.exe --headless-serve <s>   same, but keep serving for <s> seconds
//!                                       (lets CI kill the shell and verify the
//!                                       Job Object takes the whole backend tree)

use std::fs::OpenOptions;
use std::io::Write;
use std::time::{Duration, Instant};

use crate::backend::{self, Backend};

const SERVING_TIMEOUT: Duration = Duration::from_secs(300);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Smoke,
    Serve(u64),
}

pub fn parse(args: &[String]) -> Option<Mode> {
    let mut iter = args.iter().skip(1);
    while let Some(arg) = iter.next() {
        match arg.as_str() {
            "--headless-smoke" => return Some(Mode::Smoke),
            "--headless-serve" => {
                let seconds = iter.next().and_then(|v| v.parse().ok()).unwrap_or(60);
                return Some(Mode::Serve(seconds));
            }
            _ => {}
        }
    }
    None
}

fn log(message: &str) {
    let dir = backend::data_dir().join("logs");
    let _ = std::fs::create_dir_all(&dir);
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(dir.join("shell-headless.log")) {
        let secs = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or_default();
        let _ = writeln!(file, "{secs} [{}] {message}", std::process::id());
    }
}

pub fn run(mode: Mode) -> i32 {
    log(&format!("headless {mode:?} started"));
    let started = Instant::now();
    let mut backend = match Backend::spawn() {
        Ok(backend) => backend,
        Err(error) => {
            log(&format!("backend spawn failed: {error}"));
            return 2;
        }
    };
    log(&format!("backend ready file after {:.1}s", started.elapsed().as_secs_f32()));

    loop {
        if let Some(code) = backend.exited() {
            log(&format!("backend exited before serving: {code:?}"));
            return 3;
        }
        match backend.lifecycle() {
            Ok(snapshot) if snapshot.phase.is_serving() => break,
            Ok(_) | Err(_) if started.elapsed() < SERVING_TIMEOUT => std::thread::sleep(Duration::from_millis(500)),
            _ => {
                log("backend did not reach serving in time");
                backend.stop();
                return 3;
            }
        }
    }
    log(&format!("backend serving after {:.1}s", started.elapsed().as_secs_f32()));

    let status = backend.call("server_status", &[], Duration::from_secs(30));
    if status.get("running").and_then(|v| v.as_bool()) != Some(true) {
        log(&format!("POS server not running: {status}"));
        backend.stop();
        return 4;
    }

    if let Mode::Serve(seconds) = mode {
        log(&format!("serving for {seconds}s"));
        std::thread::sleep(Duration::from_secs(seconds));
    }

    let stop_started = Instant::now();
    let graceful = backend.stop();
    log(&format!("backend stopped in {:.1}s (graceful: {graceful})", stop_started.elapsed().as_secs_f32()));
    if graceful {
        0
    } else {
        5
    }
}
