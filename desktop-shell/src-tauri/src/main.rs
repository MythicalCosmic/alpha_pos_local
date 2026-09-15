// Alpha POS desktop shell.
//
// Owns the native window, the single-instance lock, the splash/loader, the tray
// icon and the windowless Python backend. Closing the panel hides it to the
// tray; the POS server keeps serving waiters and couriers until "Quit".
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend;
mod headless;
mod migration;
#[cfg(windows)]
mod job;

use std::sync::Mutex;
use std::time::{Duration, Instant};

use alphapos_shell_core::lifecycle::Phase;
use serde_json::Value;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, RunEvent, State, WebviewUrl, WebviewWindowBuilder, WindowEvent};

const SPLASH: &str = "splash";
const MAIN: &str = "main";
const TRAY_OPEN: &str = "open";
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

/// Native Yes/No confirmation without extra plugins.
#[cfg(windows)]
fn confirm_quit() -> bool {
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        MessageBoxW, IDYES, MB_DEFBUTTON2, MB_ICONWARNING, MB_SETFOREGROUND, MB_TOPMOST, MB_YESNO,
    };
    let wide = |s: &str| s.encode_utf16().chain(std::iter::once(0)).collect::<Vec<u16>>();
    let text = wide(
        "Quit Alpha POS?\n\nThe POS server will stop: waiters, couriers and other devices \
         cannot place orders until Alpha POS is opened again.",
    );
    let title = wide("Alpha POS");
    let answer = unsafe {
        MessageBoxW(
            std::ptr::null_mut(),
            text.as_ptr(),
            title.as_ptr(),
            MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2 | MB_TOPMOST | MB_SETFOREGROUND,
        )
    };
    answer == IDYES
}

#[cfg(not(windows))]
fn confirm_quit() -> bool {
    true
}

/// The mutex name used by the 1.0.x launcher and Inno Setup `AppMutex`.
#[cfg(windows)]
fn legacy_single_instance_mutex() -> windows_sys::Win32::Foundation::HANDLE {
    let name: Vec<u16> = "Global\\AlphaPOS_SingleInstance_v1".encode_utf16().chain(std::iter::once(0)).collect();
    unsafe { windows_sys::Win32::System::Threading::CreateMutexW(std::ptr::null(), 0, name.as_ptr()) }
}

fn boot(app: AppHandle) {
    // A 1.0.x update helper may be waiting for this launch to confirm health.
    let handshake = migration::LegacyHandshake::detect();
    set_splash(&app, "Starting Alpha POS…", Some(5));
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
            }
        }
        Err(error) => set_splash(&app, &format!("Could not open the panel: {error}"), None),
    }
}

fn build_tray(app: &tauri::App) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, TRAY_OPEN, "Open Alpha POS", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, TRAY_QUIT, "Quit Alpha POS", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &separator, &quit])?;

    let mut tray = TrayIconBuilder::with_id("main")
        .tooltip("Alpha POS")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            TRAY_OPEN => focus_existing(app),
            TRAY_QUIT => {
                if confirm_quit() {
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

fn main() {
    // CI/support verification: no windows, no tray, no single-instance lock.
    let args: Vec<String> = std::env::args().collect();
    if let Some(mode) = headless::parse(&args) {
        std::process::exit(headless::run(mode));
    }

    // Held for the whole process: the 1.0.x installer (AppMutex) and any stray
    // old launcher recognise a running Alpha POS by this name.
    #[cfg(windows)]
    let _legacy_mutex = legacy_single_instance_mutex();

    let app = tauri::Builder::default()
        // Must be the first plugin: a second launch only focuses this window.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| focus_existing(app)))
        .manage(Shell::default())
        .invoke_handler(tauri::generate_handler![backend_call])
        .setup(|app| {
            WebviewWindowBuilder::new(app, SPLASH, WebviewUrl::App("splash.html".into()))
                .title("Alpha POS")
                .inner_size(420.0, 260.0)
                .resizable(false)
                .decorations(false)
                .center()
                .build()?;
            build_tray(app)?;
            let handle = app.handle().clone();
            std::thread::Builder::new().name("boot".into()).spawn(move || boot(handle))?;
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
