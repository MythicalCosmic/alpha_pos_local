// Alpha POS desktop shell.
//
// Owns the native window, the single-instance lock, the splash/loader and the
// windowless Python backend. Closing the panel hides it; the POS server keeps
// serving waiters and couriers until the shell exits.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend;
#[cfg(windows)]
mod job;

use std::sync::Mutex;
use std::time::{Duration, Instant};

use alphapos_shell_core::lifecycle::Phase;
use serde_json::Value;
use tauri::{AppHandle, Manager, RunEvent, State, WebviewUrl, WebviewWindowBuilder, WindowEvent};

const SPLASH: &str = "splash";
const MAIN: &str = "main";
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

fn boot(app: AppHandle) {
    set_splash(&app, "Starting Alpha POS…", Some(5));
    let mut backend = match backend::Backend::spawn() {
        Ok(backend) => backend,
        Err(error) => {
            set_splash(&app, &format!("Could not start: {error}"), None);
            return;
        }
    };

    let deadline = Instant::now() + SERVING_WAIT;
    loop {
        if backend.exited().is_some() {
            set_splash(&app, "The POS backend stopped unexpectedly. Please reopen Alpha POS.", None);
            return;
        }
        if let Ok(snapshot) = backend.lifecycle() {
            if snapshot.phase.is_serving() {
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
        }
        Err(error) => set_splash(&app, &format!("Could not open the panel: {error}"), None),
    }
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

    app.run(|app, event| {
        if let RunEvent::Exit = event {
            let backend = app.state::<Shell>().backend.lock().unwrap().take();
            if let Some(backend) = backend {
                backend.stop();
            }
        }
    });
}
