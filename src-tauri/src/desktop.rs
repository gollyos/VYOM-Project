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
