use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Manager, WindowEvent,
};
use tauri_plugin_notification::NotificationExt;

/// System tray with the fixed action set from docs/DESKTOP_CONTROL.md.
/// Menu items other than "Open VYOM" and "Quit" are relayed to the
/// frontend as a `tray-action` event; the frontend decides how to route
/// each one (e.g. Brain API calls for pause/resume automations) so the
/// Rust layer never has to know about Brain-side business logic.
pub fn install_tray(app: &tauri::App) -> tauri::Result<()> {
    let open_item = MenuItem::with_id(app, "open_vyom", "Open VYOM", true, None::<&str>)?;
    let listen_item = MenuItem::with_id(app, "listen", "Listen", true, None::<&str>)?;
    let pause_vyom_item = MenuItem::with_id(app, "pause_vyom", "Pause VYOM", true, None::<&str>)?;
    let pause_automations_item =
        MenuItem::with_id(app, "pause_automations", "Pause Automations", true, None::<&str>)?;
    let resume_automations_item =
        MenuItem::with_id(app, "resume_automations", "Resume Automations", true, None::<&str>)?;
    let current_tasks_item = MenuItem::with_id(app, "current_tasks", "Current Tasks", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;

    let menu = Menu::with_items(
        app,
        &[
            &open_item,
            &listen_item,
            &pause_vyom_item,
            &pause_automations_item,
            &resume_automations_item,
            &current_tasks_item,
            &quit_item,
        ],
    )?;

    TrayIconBuilder::new()
        .icon(app.default_window_icon().unwrap().clone())
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open_vyom" => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
            "quit" => {
                app.exit(0);
            }
            other => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.emit("tray-action", other);
                }
            }
        })
        .build(app)?;
    Ok(())
}

/// Closing the main window follows an explicit, unsurprising preference:
/// minimize to tray. VYOM keeps running (and continues permitted
/// background work) until the user explicitly chooses Quit from the tray.
pub fn install_close_to_tray(app: &tauri::App) {
    if let Some(window) = app.get_webview_window("main") {
        let window_for_handler = window.clone();
        window.on_window_event(move |event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window_for_handler.hide();
            }
        });
    }
}

#[tauri::command]
pub fn show_native_notification(app: AppHandle, title: String, body: String) -> Result<(), String> {
    app.notification()
        .builder()
        .title(title)
        .body(body)
        .show()
        .map_err(|error| error.to_string())
}

/// Minimize VYOM's own window. Called (via the frontend bridge) when a
/// task is about to run in the BACKGROUND (see app/execution/visibility.py
/// in the Brain): VYOM works invisibly and gets out of the user's way
/// rather than keeping a window up for work the user can't see anyway.
#[tauri::command]
pub fn minimize_vyom_window(app: AppHandle) -> Result<(), String> {
    app.get_webview_window("main")
        .map(|window| window.minimize())
        .unwrap_or(Ok(()))
        .map_err(|error| error.to_string())
}

/// Restore VYOM's own window to the foreground. Called when a BACKGROUND
/// task finishes, or when the user wants VYOM back after it minimized
/// itself for a silent run.
#[tauri::command]
pub fn restore_vyom_window(app: AppHandle) -> Result<(), String> {
    let Some(window) = app.get_webview_window("main") else {
        return Ok(());
    };
    window
        .unminimize()
        .or_else(|_| window.show())
        .and_then(|_| {
            window.set_focus()?;
            Ok(())
        })
        .map_err(|error| error.to_string())
}

/// Toggle maximize/restore on VYOM's own window. Since the window runs
/// with `decorations: false` (a fully custom titlebar), there is no OS
/// double-click-to-maximize or native maximize button — the frontend's
/// custom titlebar calls this directly.
#[tauri::command]
pub fn toggle_maximize_vyom_window(app: AppHandle) -> Result<(), String> {
    let Some(window) = app.get_webview_window("main") else {
        return Ok(());
    };
    let is_maximized = window.is_maximized().map_err(|error| error.to_string())?;
    if is_maximized {
        window.unmaximize().map_err(|error| error.to_string())
    } else {
        window.maximize().map_err(|error| error.to_string())
    }
}

/// Close VYOM's own window: a genuine quit; the frontend's custom
/// titlebar calls this because with `decorations: false` there is no
/// native close button. Note this is intentionally different from the
/// tray's "minimize to tray" `CloseRequested` interception (which
/// catches the OS-level close signal, e.g. Alt+F4) — a user who
/// deliberately clicks a close button in VYOM's own UI expects the app
/// to actually exit, not vanish into the tray.
#[tauri::command]
pub fn close_vyom_window(app: AppHandle) -> Result<(), String> {
    app.exit(0);
    Ok(())
}
