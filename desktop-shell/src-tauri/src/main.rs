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
mod updates;

use std::path::Path;
use std::sync::atomic::Ordering;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use alphapos_shell_core::lifecycle::Phase;
use alphapos_shell_core::update_policy::{self, DownloadMode, StartupDecision};
use serde_json::Value;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, RunEvent, State, WebviewUrl, WebviewWindowBuilder, WindowEvent};

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
    backend: Mutex<Option<backend::Backend>>,
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
        Phase::Booting => ("Starting Alpha POS…", 15),
        Phase::Database => ("Starting the database…", 35),
        Phase::Migrating => ("Preparing the POS server…", 65),
        Phase::Serving => ("Ready", 100),
        Phase::Stopping => ("Stopping…", 100),
        Phase::Error => ("Still starting — retrying…", 50),
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

const QUIT_WARNING: &str = "The POS server will stop: waiters, couriers and other devices cannot place orders \
     until Alpha POS is running again.";

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
    set_splash(app, &format!("Installing update {}…", staged.version), Some(95));
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
            set_splash(app, "Checking for updates…", Some(8));
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
                let percent = total.map(|t| (downloaded.min(t) * 100 / t.max(1)) as u8).unwrap_or(0);
                set_splash(app, &format!("Downloading update {version}…"), Some(10 + percent * 8 / 10));
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
        if let Some(update) = updates::check_remote(&app, &state.blocked_versions) {
            let progress = updates::start_download(data_dir.clone(), update);
            while !progress.done.load(Ordering::Relaxed) {
                std::thread::sleep(Duration::from_secs(5));
            }
        }
    }
}

fn restart_into_update(app: &AppHandle) {
    let data_dir = backend::data_dir();
    let Some(staged) = updates::installable_staged(&data_dir) else {
        message_box("Alpha POS is up to date. New versions are downloaded automatically.", false);
        return;
    };
    let question = format!("Install Alpha POS {} now?\n\n{QUIT_WARNING}\nIt restarts by itself when the update is installed.", staged.version);
    if !message_box(&question, true) {
        return;
    }
    // Stop the backend first so the guard finds nothing running.
    if let Some(backend) = app.state::<Shell>().backend.lock().unwrap().take() {
        backend.stop();
    }
    if updates::launch_guard(&data_dir, &staged).is_ok() {
        app.exit(0);
    } else {
        message_box("The update could not be started. Please try again later.", false);
    }
}

fn boot(app: AppHandle, post_update: Option<String>) {
    // A 1.0.x update helper may be waiting for this launch to confirm health.
    let handshake = migration::LegacyHandshake::detect();
    let data_dir = backend::data_dir();
    set_splash(&app, "Starting Alpha POS…", Some(5));
    if !run_startup_update(&app, &data_dir, &handshake, post_update.is_some()) {
        return;
    }

    let mut backend = match backend::Backend::spawn() {
        Ok(backend) => backend,
        Err(error) => {
            set_splash(&app, &format!("Could not start: {error}"), None);
            return;
        }
    };

    let deadline = Instant::now() + SERVING_WAIT;
    let mut serving = false;
    loop {
        if backend.exited().is_some() {
            set_splash(&app, "The POS backend stopped unexpectedly. Please reopen Alpha POS.", None);
            return;
        }
        if let Ok(snapshot) = backend.lifecycle() {
            if snapshot.phase.is_serving() {
                serving = true;
                break;
            }
            let (text, progress) = phase_text(snapshot.phase);
            set_splash(&app, text, Some(progress));
        }
        if Instant::now() >= deadline {
            break;
        }
        std::thread::sleep(Duration::from_millis(300));
    }

    let url = backend.url();
    app.state::<Shell>().backend.lock().unwrap().replace(backend);

    let Ok(url) = tauri::Url::parse(&url) else { return };
    let built = WebviewWindowBuilder::new(&app, MAIN, WebviewUrl::External(url))
        .title("Alpha POS")
        .inner_size(1180.0, 780.0)
        .min_inner_size(900.0, 640.0)
        .center()
        .build();
    match built {
        Ok(_) => {
            if let Some(splash) = app.get_webview_window(SPLASH) {
                let _ = splash.close();
            }
            if serving {
                handshake.confirm_serving();
                if let Some(version) = &post_update {
                    updates::confirm_post_update(&data_dir, version);
                }
            }
        }
        Err(error) => set_splash(&app, &format!("Could not open the panel: {error}"), None),
    }

    let checker = app.clone();
    let _ = std::thread::Builder::new().name("update-checks".into()).spawn(move || background_update_checks(checker));
}

fn build_tray(app: &tauri::App) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, TRAY_OPEN, "Open Alpha POS", true, None::<&str>)?;
    let update = MenuItem::with_id(app, TRAY_UPDATE, "Restart to update", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, TRAY_QUIT, "Quit Alpha POS", true, None::<&str>)?;
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
                if message_box(&format!("Quit Alpha POS?\n\n{QUIT_WARNING}"), true) {
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
async fn backend_call(shell: State<'_, Shell>, method: String, args: Option<Vec<Value>>) -> Result<Value, ()> {
    let args = args.unwrap_or_default();
    let guard = shell.backend.lock().unwrap();
    let Some(backend) = guard.as_ref() else {
        return Ok(backend::error_value("backend_unavailable", "The POS backend is not running"));
    };
    Ok(backend.call(&method, &args, backend::call_timeout(&method)))
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
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to build Alpha POS shell");

    app.run(|app, event| match event {
        // Hiding the last window must not end the app; only tray Quit exits.
        RunEvent::ExitRequested { code: None, api, .. } => api.prevent_exit(),
        RunEvent::Exit => {
            let backend = app.state::<Shell>().backend.lock().unwrap().take();
            if let Some(backend) = backend {
                backend.stop();
            }
        }
        _ => {}
    });
}
