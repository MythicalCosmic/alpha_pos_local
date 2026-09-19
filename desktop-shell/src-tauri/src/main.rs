// Alpha POS desktop shell.
//
// Owns the native window, the single-instance lock, the splash/loader, the tray
// icon, startup updates and the windowless Python backend. Closing the panel
// hides it to the tray; the POS server keeps serving waiters and couriers until
// "Quit".
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend;
mod headless;
#[cfg(windows)]
mod job;
mod migration;
mod texts;
mod updates;

use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use alphapos_shell_core::backoff::{CrashBreaker, Verdict};
use alphapos_shell_core::lifecycle::Phase;
use alphapos_shell_core::update_policy::{self, DownloadMode, StartupDecision};
use serde_json::Value;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, RunEvent, State, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use texts::{text, Lang, Msg};

const SPLASH: &str = "splash";
const MAIN: &str = "main";
const TRAY_OPEN: &str = "open";
const TRAY_UPDATE: &str = "update";
const TRAY_QUIT: &str = "quit";
/// Show the panel even if setup is still running after this long; the panel
/// reports the backend phase itself.
const SERVING_WAIT: Duration = Duration::from_secs(120);

#[derive(Default)]
struct Shell {
    /// The running backend process (owned: stopping it needs `&mut`).
    backend: Mutex<Option<backend::Backend>>,
    /// Where it listens. Panel calls clone this and never hold `backend`,
    /// so one slow call can no longer stall every other screen.
    connection: Mutex<Option<backend::Connection>>,
    /// Set while quitting or installing an update: do not restart the backend.
    stopping: AtomicBool,
}

impl Shell {
    fn connection(&self) -> Option<backend::Connection> {
        self.connection.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }

    fn install(&self, backend: backend::Backend) {
        *self.connection.lock().unwrap_or_else(|e| e.into_inner()) = Some(backend.connection());
        *self.backend.lock().unwrap_or_else(|e| e.into_inner()) = Some(backend);
    }

    fn take(&self) -> Option<backend::Backend> {
        *self.connection.lock().unwrap_or_else(|e| e.into_inner()) = None;
        self.backend.lock().unwrap_or_else(|e| e.into_inner()).take()
    }
}

fn lang() -> Lang {
    texts::lang(&backend::data_dir())
}

fn t(msg: Msg) -> &'static str {
    text(lang(), msg)
}

fn focus_existing(app: &AppHandle) {
    for label in [MAIN, SPLASH] {
        if let Some(window) = app.get_webview_window(label) {
            let _ = window.unminimize();
            let _ = window.show();
            let _ = window.set_focus();
            return;
        }
    }
}

fn set_splash(app: &AppHandle, text: &str, progress: Option<u8>) {
    if let Some(window) = app.get_webview_window(SPLASH) {
        let text = serde_json::to_string(text).unwrap_or_else(|_| "\"\"".into());
        let progress = progress.map(|p| p.to_string()).unwrap_or_else(|| "null".into());
        let _ = window.eval(&format!("window.setStatus && window.setStatus({text}, {progress})"));
    }
}

fn phase_text(phase: Phase) -> (&'static str, u8) {
    match phase {
        Phase::Booting => (t(Msg::Starting), 15),
        Phase::Database => (t(Msg::Database), 35),
        Phase::Migrating => (t(Msg::Preparing), 65),
        Phase::Serving => (t(Msg::Ready), 100),
        Phase::Stopping => (t(Msg::Stopping), 100),
        Phase::Error => (t(Msg::StillStarting), 50),
    }
}

/// Native message box without extra plugins. Returns true for Yes/OK.
#[cfg(windows)]
fn message_box(text: &str, question: bool) -> bool {
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        MessageBoxW, IDOK, IDYES, MB_DEFBUTTON2, MB_ICONINFORMATION, MB_ICONWARNING, MB_OK, MB_SETFOREGROUND,
        MB_TOPMOST, MB_YESNO,
    };
    let wide = |s: &str| s.encode_utf16().chain(std::iter::once(0)).collect::<Vec<u16>>();
    let text = wide(text);
    let title = wide("Alpha POS");
    let style = if question {
        MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2
    } else {
        MB_OK | MB_ICONINFORMATION
    };
    let answer = unsafe {
        MessageBoxW(std::ptr::null_mut(), text.as_ptr(), title.as_ptr(), style | MB_TOPMOST | MB_SETFOREGROUND)
    };
    answer == IDYES || answer == IDOK
}

#[cfg(not(windows))]
fn message_box(_text: &str, _question: bool) -> bool {
    true
}


/// The mutex name used by the 1.0.x launcher and Inno Setup `AppMutex`.
#[cfg(windows)]
fn legacy_single_instance_mutex() -> windows_sys::Win32::Foundation::HANDLE {
    let name: Vec<u16> = "Global\\AlphaPOS_SingleInstance_v1".encode_utf16().chain(std::iter::once(0)).collect();
    unsafe { windows_sys::Win32::System::Threading::CreateMutexW(std::ptr::null(), 0, name.as_ptr()) }
}

/// Hand a staged update to the guard and exit. Returns false if the app is
/// now exiting.
fn install_staged(app: &AppHandle, data_dir: &Path) -> bool {
    let Some(staged) = updates::installable_staged(data_dir) else { return true };
    set_splash(app, &format!("{} {}…", t(Msg::InstallingUpdate), staged.version), Some(95));
    match updates::launch_guard(data_dir, &staged) {
        Ok(()) => {
            app.exit(0);
            false
        }
        Err(_) => true,
    }
}

/// Startup update step, before the backend starts. Returns false if the app is
/// exiting to install an update.
fn run_startup_update(app: &AppHandle, data_dir: &Path, handshake: &migration::LegacyHandshake, post_update: bool) -> bool {
    let (decision, state) = updates::startup_decision(data_dir, handshake.flag(), post_update);
    match decision {
        StartupDecision::StartWithoutUpdates(_) => true,
        StartupDecision::InstallStaged { .. } => install_staged(app, data_dir),
        StartupDecision::CheckRemote { discard_staged } => {
            if discard_staged {
                updates::discard_staged(data_dir);
            }
            set_splash(app, t(Msg::CheckingUpdates), Some(8));
            let Some(update) = updates::check_remote(app, &state.blocked_versions) else { return true };
            let version = update.version.clone();
            let progress = updates::start_download(data_dir.to_path_buf(), update);
            let started = Instant::now();
            loop {
                if progress.done.load(Ordering::Relaxed) {
                    let finished = matches!(progress.result.lock().unwrap().as_ref(), Some(Ok(())));
                    return if finished { install_staged(app, data_dir) } else { true };
                }
                let downloaded = progress.downloaded.load(Ordering::Relaxed);
                let total = progress.total();
                if update_policy::download_mode(downloaded, total, started.elapsed()) == DownloadMode::Background {
                    // Keeps downloading; installs on the next launch or via
                    // "Restart to update".
                    return true;
                }
                // u64 maths: 10 + 80 % of the download, never above 90.
                let percent = total.map(|total| downloaded.min(total) * 100 / total.max(1)).unwrap_or(0);
                let bar = (10 + percent.min(100) * 8 / 10) as u8;
                set_splash(app, &format!("{} {version}…", t(Msg::DownloadingUpdate)), Some(bar));
                std::thread::sleep(Duration::from_millis(200));
            }
        }
    }
}

/// Every few hours: download and stage only, never restart on our own.
fn background_update_checks(app: AppHandle) {
    let data_dir = backend::data_dir();
    loop {
        std::thread::sleep(updates::BACKGROUND_CHECK_EVERY);
        if updates::installable_staged(&data_dir).is_some() {
            continue;
        }
        let state = alphapos_update::UpdateState::load(&alphapos_update::state_path(&data_dir));
        match updates::check_remote_within(&app, &state.blocked_versions, Duration::from_secs(30)) {
            Ok(Some(update)) => {
                let progress = updates::start_download(data_dir.clone(), update);
                while !progress.done.load(Ordering::Relaxed) {
                    std::thread::sleep(Duration::from_secs(5));
                }
                let outcome = progress.result.lock().unwrap_or_else(|e| e.into_inner()).clone();
                updates::publish_status(&data_dir, Some(outcome.unwrap_or(Ok(()))));
            }
            Ok(None) => updates::publish_status(&data_dir, Some(Ok(()))),
            Err(error) => updates::publish_status(&data_dir, Some(Err(error))),
        }
    }
}

fn restart_into_update(app: &AppHandle) {
    let data_dir = backend::data_dir();
    let Some(staged) = updates::installable_staged(&data_dir) else {
        message_box(t(Msg::UpToDate), false);
        return;
    };
    let question = format!(
        "{}\n\n{}",
        t(Msg::InstallQuestion).replace("{version}", &staged.version),
        t(Msg::QuitWarning),
    );
    if !message_box(&question, true) {
        return;
    }
    let shell = app.state::<Shell>();
    // Stop the backend first so the guard finds nothing running.
    shell.stopping.store(true, Ordering::SeqCst);
    if let Some(backend) = shell.take() {
        backend.stop();
    }
    if updates::launch_guard(&data_dir, &staged).is_ok() {
        app.exit(0);
    } else {
        // Never leave the floor without a POS server: the supervisor restarts it.
        shell.stopping.store(false, Ordering::SeqCst);
        message_box(t(Msg::UpdateCouldNotStart), false);
    }
}

/// Start the backend, asking the operator to retry instead of leaving a dead
/// splash. `None` only when the operator declined a retry (the app exits).
fn spawn_backend_with_retry(app: &AppHandle) -> Option<backend::Backend> {
    loop {
        match backend::Backend::spawn() {
            Ok(backend) => return Some(backend),
            Err(error) => {
                let reason = match error {
                    backend::StartError::ExitedEarly(Some(2)) => t(Msg::AlreadyRunning).to_string(),
                    other => format!("{}\n\n{other}", t(Msg::CouldNotStart)),
                };
                set_splash(app, &reason, None);
                if !message_box(&format!("{reason}\n\n{}", t(Msg::TryAgain)), true) {
                    app.exit(1);
                    return None;
                }
                set_splash(app, t(Msg::Starting), Some(5));
            }
        }
    }
}

/// Keep the POS server alive after the window opened: restart a crashed
/// backend with backoff, confirm a fresh update once it serves (however slow
/// the first boot is), and carry out the panel's update requests.
fn supervise(app: AppHandle, mut confirm: Option<Box<dyn FnOnce() + Send>>) {
    let started = Instant::now();
    let mut breaker = CrashBreaker::default();
    let mut warned = false;
    let mut seen_check = None;
    let mut seen_restart = None;
    loop {
        std::thread::sleep(Duration::from_millis(700));
        let shell = app.state::<Shell>();
        if shell.stopping.load(Ordering::SeqCst) {
            continue;
        }
        let exited = {
            let mut guard = shell.backend.lock().unwrap_or_else(|e| e.into_inner());
            match guard.as_mut() {
                Some(backend) => backend.exited().is_some(),
                None => true,
            }
        };
        if exited {
            // Dropping the old handle closes its job: nothing of it survives.
            drop(shell.take());
            let delay = match breaker.record(started.elapsed()) {
                Verdict::Restart(delay) => delay,
                Verdict::GiveUp => {
                    if !warned {
                        warned = true;
                        let _ = std::thread::Builder::new()
                            .name("backend-warning".into())
                            .spawn(|| { message_box(t(Msg::BackendKeepsStopping), false); });
                    }
                    alphapos_shell_core::backoff::MAX_DELAY
                }
            };
            std::thread::sleep(delay);
            if shell.stopping.load(Ordering::SeqCst) {
                continue;
            }
            match backend::Backend::spawn() {
                Ok(backend) => {
                    let url = backend.url();
                    shell.install(backend);
                    seen_check = None;
                    seen_restart = None;
                    if let (Some(window), Ok(url)) = (app.get_webview_window(MAIN), tauri::Url::parse(&url)) {
                        let _ = window.navigate(url);
                    }
                }
                Err(_) => continue,
            }
            continue;
        }
        let Some(conn) = shell.connection() else { continue };
        let Ok(snapshot) = conn.lifecycle() else { continue };
        if snapshot.phase.is_serving() {
            if let Some(confirm) = confirm.take() {
                confirm();
            }
            // Serving again: earlier crashes no longer count towards giving up.
            if breaker.recent_crashes() > 0 {
                breaker.reset();
            }
        }
        // The first snapshot of a backend only records where its counters are.
        let check = snapshot.update_check_seq;
        if seen_check.is_some_and(|seen| check > seen) {
            updates::check_and_stage_in_background(app.clone(), backend::data_dir());
        }
        seen_check = Some(check);
        let restart = snapshot.update_restart_seq;
        if seen_restart.is_some_and(|seen| restart > seen) {
            let handle = app.clone();
            let _ = std::thread::Builder::new().name("restart-to-update".into()).spawn(move || restart_into_update(&handle));
        }
        seen_restart = Some(restart);
    }
}

/// Open the panel at a size that fits the screen (a 1366x768 till at 125 %).
fn open_panel(app: &AppHandle, url: tauri::Url) -> tauri::Result<()> {
    let window = WebviewWindowBuilder::new(app, MAIN, WebviewUrl::External(url))
        .title("Alpha POS")
        .inner_size(1180.0, 780.0)
        .min_inner_size(800.0, 560.0)
        .center()
        .build()?;
    if let Ok(Some(monitor)) = window.current_monitor() {
        let size = monitor.size().to_logical::<f64>(monitor.scale_factor());
        if size.width < 1240.0 || size.height < 840.0 {
            let _ = window.maximize();
        }
    }
    Ok(())
}

fn boot(app: AppHandle, post_update: Option<String>) {
    // A 1.0.x update helper may be waiting for this launch to confirm health.
    let handshake = migration::LegacyHandshake::detect();
    let data_dir = backend::data_dir();
    set_splash(&app, t(Msg::Starting), Some(5));
    if !run_startup_update(&app, &data_dir, &handshake, post_update.is_some()) {
        return;
    }
    updates::publish_status(&data_dir, None);

    let mut backend = loop {
        let Some(mut backend) = spawn_backend_with_retry(&app) else { return };
        let deadline = Instant::now() + SERVING_WAIT;
        let mut exited = false;
        loop {
            if backend.exited().is_some() {
                exited = true;
                break;
            }
            if let Ok(snapshot) = backend.lifecycle() {
                if snapshot.phase.is_serving() {
                    break;
                }
                let (text, progress) = phase_text(snapshot.phase);
                set_splash(&app, if snapshot.phase == Phase::Error && !snapshot.detail.is_empty() { &snapshot.detail } else { text }, Some(progress));
            }
            if Instant::now() >= deadline {
                break;
            }
            std::thread::sleep(Duration::from_millis(300));
        }
        if !exited {
            break backend;
        }
        let reason = t(Msg::BackendStopped);
        set_splash(&app, reason, None);
        if !message_box(&format!("{}\n\n{}", t(Msg::CouldNotStart), t(Msg::TryAgain)), true) {
            app.exit(1);
            return;
        }
    };
    let _ = backend.exited();

    let url = backend.url();
    app.state::<Shell>().install(backend);

    let Ok(url) = tauri::Url::parse(&url) else { return };
    match open_panel(&app, url) {
        Ok(()) => {
            if let Some(splash) = app.get_webview_window(SPLASH) {
                let _ = splash.close();
            }
        }
        Err(error) => set_splash(&app, &format!("{}\n\n{error}", t(Msg::CouldNotStart)), None),
    }

    // Confirm the launch (1.0.x helper) and a fresh update as soon as the
    // backend serves, even when that takes longer than the splash waited.
    let confirm_dir = data_dir.clone();
    let confirm: Box<dyn FnOnce() + Send> = Box::new(move || {
        handshake.confirm_serving();
        if let Some(version) = &post_update {
            updates::confirm_post_update(&confirm_dir, version);
        }
        updates::publish_status(&confirm_dir, None);
    });
    let supervisor = app.clone();
    let _ = std::thread::Builder::new().name("supervisor".into()).spawn(move || supervise(supervisor, Some(confirm)));

    let checker = app.clone();
    let _ = std::thread::Builder::new().name("update-checks".into()).spawn(move || background_update_checks(checker));
}

fn build_tray(app: &tauri::App) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, TRAY_OPEN, t(Msg::TrayOpen), true, None::<&str>)?;
    let update = MenuItem::with_id(app, TRAY_UPDATE, t(Msg::TrayUpdate), true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, TRAY_QUIT, t(Msg::TrayQuit), true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &update, &separator, &quit])?;

    let mut tray = TrayIconBuilder::with_id("main")
        .tooltip("Alpha POS")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            TRAY_OPEN => focus_existing(app),
            TRAY_UPDATE => {
                let handle = app.clone();
                let _ = std::thread::Builder::new().name("restart-to-update".into()).spawn(move || restart_into_update(&handle));
            }
            TRAY_QUIT => {
                if message_box(&format!("{}\n\n{}", t(Msg::QuitQuestion), t(Msg::QuitWarning)), true) {
                    app.state::<Shell>().stopping.store(true, Ordering::SeqCst);
                    app.exit(0);
                }
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                focus_existing(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

#[tauri::command]
async fn backend_call(
    shell: State<'_, Shell>,
    method: String,
    args: Option<Vec<Value>>,
    timeout_ms: Option<u64>,
) -> Result<Value, ()> {
    let args = args.unwrap_or_default();
    let Some(conn) = shell.connection() else {
        return Ok(backend::error_value("backend_unavailable", "The POS backend is not running"));
    };
    let timeout = backend::call_timeout(&method, timeout_ms);
    // Blocking HTTP runs on the blocking pool so it cannot starve the runtime.
    let value = tauri::async_runtime::spawn_blocking(move || conn.call(&method, &args, timeout))
        .await
        .unwrap_or_else(|error| backend::error_value("backend_unavailable", &error.to_string()));
    Ok(value)
}

#[tauri::command]
fn update_state() -> Value {
    let data_dir = backend::data_dir();
    let staged = updates::installable_staged(&data_dir);
    let state = alphapos_update::UpdateState::load(&alphapos_update::state_path(&data_dir));
    serde_json::json!({
        "ok": true,
        "current_version": updates::CURRENT_VERSION,
        "staged_version": staged.map(|s| s.version),
        "blocked_versions": state.blocked_versions,
        "last_rollback": state.last_rollback,
    })
}

/// Called by the panel's Tauri transport (`invoke('restart_to_update')`).
#[tauri::command]
fn restart_to_update(app: AppHandle) {
    let _ = std::thread::Builder::new().name("restart-to-update".into()).spawn(move || restart_into_update(&app));
}

fn main() {
    // CI/support verification: no windows, no tray, no single-instance lock.
    let args: Vec<String> = std::env::args().collect();
    if let Some(mode) = headless::parse(&args) {
        std::process::exit(headless::run(mode));
    }
    let post_update = args.windows(2).find(|pair| pair[0] == "--post-update").map(|pair| pair[1].clone());

    // Without WebView2 the window cannot be created and the app would vanish
    // silently (the build aborts on panic): explain what to install instead.
    if tauri::webview_version().is_err() {
        message_box(t(Msg::WebView2Missing), false);
        std::process::exit(1);
    }

    // Held for the whole process: the 1.0.x installer (AppMutex) and any stray
    // old launcher recognise a running Alpha POS by this name.
    #[cfg(windows)]
    let _legacy_mutex = legacy_single_instance_mutex();

    let app = tauri::Builder::default()
        // Must be the first plugin: a second launch only focuses this window.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| focus_existing(app)))
        .plugin(tauri_plugin_updater::Builder::new().pubkey(updates::PUBKEY).build())
        .manage(Shell::default())
        .invoke_handler(tauri::generate_handler![backend_call, update_state, restart_to_update])
        .setup(move |app| {
            WebviewWindowBuilder::new(app, SPLASH, WebviewUrl::App("splash.html".into()))
                .title("Alpha POS")
                .inner_size(420.0, 260.0)
                .resizable(false)
                .decorations(false)
                .center()
                .build()?;
            build_tray(app)?;
            let handle = app.handle().clone();
            let post_update = post_update.clone();
            std::thread::Builder::new().name("boot".into()).spawn(move || boot(handle, post_update))?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == MAIN {
                    // Hide instead of quitting: the POS keeps serving the floor.
                    api.prevent_close();
                    let _ = window.hide();
                } else if window.label() == SPLASH && window.app_handle().get_webview_window(MAIN).is_none() {
                    // Alt+F4 on the loader would leave nothing to reopen.
                    api.prevent_close();
                    let _ = window.minimize();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to build Alpha POS shell");

    app.run(|app, event| match event {
        // Hiding the last window must not end the app; only tray Quit exits.
        RunEvent::ExitRequested { code: None, api, .. } => api.prevent_exit(),
        RunEvent::Exit => {
            let shell = app.state::<Shell>();
            shell.stopping.store(true, Ordering::SeqCst);
            if let Some(backend) = shell.take() {
                backend.stop();
            }
        }
        _ => {}
    });
}
