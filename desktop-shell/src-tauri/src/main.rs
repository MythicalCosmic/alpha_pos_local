// Alpha POS desktop shell.
//
// Owns the native window, the single-instance lock, the splash/loader and (in
// later phases) the windowless Python backend and startup updates.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

const SPLASH: &str = "splash";
const MAIN: &str = "main";

fn focus_existing(app: &tauri::AppHandle) {
    for label in [MAIN, SPLASH] {
        if let Some(window) = app.get_webview_window(label) {
            let _ = window.unminimize();
            let _ = window.show();
            let _ = window.set_focus();
            return;
        }
    }
}

fn main() {
    tauri::Builder::default()
        // Must be the first plugin: a second launch only focuses this window.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| focus_existing(app)))
        .setup(|app| {
            WebviewWindowBuilder::new(app, SPLASH, WebviewUrl::App("splash.html".into()))
                .title("Alpha POS")
                .inner_size(420.0, 260.0)
                .resizable(false)
                .decorations(false)
                .center()
                .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("failed to run Alpha POS shell");
}
