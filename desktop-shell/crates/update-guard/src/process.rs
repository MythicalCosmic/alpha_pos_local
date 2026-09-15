//! Windows side of the guard: processes, installer runs and rollback.

use std::fs;
use std::path::Path;
use std::process::Command;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use alphapos_shell_core::paths::is_under;
use alphapos_update::{
    confirm_marker, installer_args, state_path, verify_signature, wait_for_health, HealthResult, Rollback, UpdateState,
    HEALTH_TIMEOUT, INSTALL_TIMEOUT, SHELL_EXIT_TIMEOUT, TRUSTED_PUBLIC_KEYS,
};
use windows_sys::Win32::Foundation::{CloseHandle, WAIT_OBJECT_0};
use windows_sys::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
};
use windows_sys::Win32::System::Threading::{
    OpenProcess, QueryFullProcessImageNameW, TerminateProcess, WaitForSingleObject, PROCESS_QUERY_LIMITED_INFORMATION,
    PROCESS_SYNCHRONIZE, PROCESS_TERMINATE,
};

use crate::Args;

const CREATE_NO_WINDOW: u32 = 0x0800_0000;

fn wait_pid_exit(pid: u32, timeout: Duration) -> bool {
    unsafe {
        let handle = OpenProcess(PROCESS_SYNCHRONIZE, 0, pid);
        if handle.is_null() {
            return true; // already gone
        }
        let result = WaitForSingleObject(handle, timeout.as_millis().min(u32::MAX as u128) as u32);
        CloseHandle(handle);
        result == WAIT_OBJECT_0
    }
}

fn image_path(pid: u32) -> Option<String> {
    unsafe {
        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if handle.is_null() {
            return None;
        }
        let mut buffer = vec![0u16; 32_768];
        let mut size = buffer.len() as u32;
        let ok = QueryFullProcessImageNameW(handle, 0, buffer.as_mut_ptr(), &mut size);
        CloseHandle(handle);
        (ok != 0).then(|| String::from_utf16_lossy(&buffer[..size as usize]))
    }
}

/// Terminate every process whose image lives under the install directory.
fn kill_under(install_dir: &Path, log: &dyn Fn(&str)) -> usize {
    let root = install_dir.display().to_string();
    let own_pid = std::process::id();
    let mut killed = 0;
    unsafe {
        let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if snapshot.is_null() || snapshot as isize == -1 {
            return 0;
        }
        let mut entry: PROCESSENTRY32W = std::mem::zeroed();
        entry.dwSize = std::mem::size_of::<PROCESSENTRY32W>() as u32;
        let mut more = Process32FirstW(snapshot, &mut entry) != 0;
        while more {
            let pid = entry.th32ProcessID;
            if pid != own_pid {
                if let Some(path) = image_path(pid) {
                    if is_under(&path, &root) {
                        let handle = OpenProcess(PROCESS_TERMINATE | PROCESS_SYNCHRONIZE, 0, pid);
                        if !handle.is_null() {
                            TerminateProcess(handle, 1);
                            WaitForSingleObject(handle, 5_000);
                            CloseHandle(handle);
                            killed += 1;
                            log(&format!("terminated leftover process {pid} {path}"));
                        }
                    }
                }
            }
            more = Process32NextW(snapshot, &mut entry) != 0;
        }
        CloseHandle(snapshot);
    }
    killed
}

fn verified(installer: &Path, signature: &Path) -> Result<(), String> {
    let data = fs::read(installer).map_err(|e| format!("cannot read installer: {e}"))?;
    let sig = fs::read_to_string(signature).map_err(|e| format!("cannot read signature: {e}"))?;
    verify_signature(TRUSTED_PUBLIC_KEYS, &sig, &data).map_err(|e| format!("installer signature rejected: {e:?}"))
}

fn run_installer(installer: &Path, install_dir: &Path, log: &dyn Fn(&str)) -> Result<(), String> {
    use std::os::windows::process::CommandExt;
    log(&format!("running installer {}", installer.display()));
    let mut child = Command::new(installer)
        .args(installer_args(install_dir))
        .creation_flags(CREATE_NO_WINDOW)
        .spawn()
        .map_err(|e| format!("cannot start installer: {e}"))?;
    let deadline = Instant::now() + INSTALL_TIMEOUT;
    loop {
        match child.try_wait() {
            Ok(Some(status)) if status.success() => return Ok(()),
            Ok(Some(status)) => return Err(format!("installer exited with {status}")),
            Ok(None) if Instant::now() >= deadline => {
                let _ = child.kill();
                return Err("installer timed out".into());
            }
            Ok(None) => std::thread::sleep(Duration::from_millis(250)),
            Err(e) => return Err(format!("installer wait failed: {e}")),
        }
    }
}

fn installed_version(install_dir: &Path) -> Option<String> {
    fs::read_to_string(install_dir.join("version.txt")).ok().map(|v| v.trim().to_string())
}

fn launch_and_confirm(args: &Args, version: &str, log: &dyn Fn(&str)) -> HealthResult {
    let marker = confirm_marker(&args.data_dir, version);
    let _ = fs::remove_file(&marker);
    let shell = args.install_dir.join("AlphaPOS.exe");
    let mut child = match Command::new(&shell).arg("--post-update").arg(version).current_dir(&args.data_dir).spawn() {
        Ok(child) => child,
        Err(error) => {
            log(&format!("cannot launch {}: {error}", shell.display()));
            return HealthResult::Exited(None);
        }
    };
    wait_for_health(
        HEALTH_TIMEOUT,
        Duration::from_millis(500),
        || marker.exists(),
        || match child.try_wait() {
            Ok(Some(status)) => Some(status.code()),
            Ok(None) => None,
            Err(_) => Some(None),
        },
        std::thread::sleep,
        Instant::now,
    )
}

fn install(args: &Args, installer: &Path, signature: &Path, version: &str, log: &dyn Fn(&str)) -> Result<HealthResult, String> {
    verified(installer, signature)?;
    kill_under(&args.install_dir, log);
    run_installer(installer, &args.install_dir, log)?;
    match installed_version(&args.install_dir) {
        Some(found) if found == version => {}
        found => return Err(format!("installed version is {found:?}, expected {version}")),
    }
    Ok(launch_and_confirm(args, version, log))
}

pub fn run(args: &Args, log: &dyn Fn(&str)) -> i32 {
    log(&format!("guard started: {} -> {}", args.from_version, args.version));
    if !wait_pid_exit(args.shell_pid, SHELL_EXIT_TIMEOUT) {
        log("shell did not exit in time; terminating processes from the install folder");
    }
    // Includes a slow-to-exit shell and anything that escaped its job.
    kill_under(&args.install_dir, log);

    let state_file = state_path(&args.data_dir);
    let mut state = UpdateState::load(&state_file);
    state.pending_confirmation = Some(args.version.clone());
    let _ = state.save(&state_file);

    let failure = match install(args, &args.installer, &args.signature, &args.version, log) {
        Ok(HealthResult::Confirmed) => {
            log(&format!("{} confirmed healthy", args.version));
            state.pending_confirmation = None;
            let _ = state.save(&state_file);
            return 0;
        }
        Ok(other) => format!("new version did not confirm: {other:?}"),
        Err(error) => error,
    };
    log(&format!("update failed: {failure}"));

    state.block(&args.version);
    state.pending_confirmation = None;
    state.last_rollback = Some(Rollback {
        from_version: args.version.clone(),
        to_version: args.from_version.clone(),
        reason: failure.clone(),
        at_unix: SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or_default(),
    });
    let _ = state.save(&state_file);

    let Some((lkg_installer, lkg_signature)) = &args.lkg else {
        log("no last-known-good installer available; leaving the current files in place");
        return 10;
    };
    kill_under(&args.install_dir, log);
    match install(args, lkg_installer, lkg_signature, &args.from_version, log) {
        Ok(HealthResult::Confirmed) => {
            log(&format!("rolled back to {}", args.from_version));
            11
        }
        Ok(other) => {
            log(&format!("rollback started but did not confirm: {other:?}"));
            12
        }
        Err(error) => {
            log(&format!("rollback failed: {error}"));
            13
        }
    }
}
