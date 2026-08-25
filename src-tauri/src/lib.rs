use tauri::{Emitter, Manager};
use tauri_plugin_global_shortcut::ShortcutState;

mod brain;
mod desktop;
mod voice;

const EMERGENCY_PAUSE_SHORTCUT: &str = "CommandOrControl+Shift+Escape";

fn install_tls_crypto_provider() {
    let _ = rustls::crypto::ring::default_provider().install_default();
}

// The Python Brain service already persists provider keys in
// `services/brain/.env` (loaded via python-dotenv). The native voice
// bridge (voice.rs) reads GEMINI_API_KEY straight from the OS process
// environment, so without this it never saw that file and the key had to
// be re-exported in every terminal session. Loading the same `.env` here
// means the user maintains exactly one file for both processes.
// `CARGO_MANIFEST_DIR` is baked in at compile time as this crate's
// absolute path (`src-tauri/`), so this resolves correctly regardless of
// the process's working directory in both dev and release builds.
// `dotenvy::from_path` never overwrites a variable already present in the
// environment, matching python-dotenv's `override=False` behavior.
fn load_local_env_file() {
    let manifest_dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let candidates = [
        manifest_dir.join("../services/brain/.env"),
        manifest_dir.join("../.env"),
    ];
    for candidate in candidates {
        if candidate.is_file() {
            let _ = dotenvy::from_path(&candidate);
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    load_local_env_file();
    // tokio-tungstenite intentionally disables rustls' default crypto backend.
    // Select one before any TLS client configuration is constructed.
    install_tls_crypto_provider();

    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, shortcut, event| {
                    if shortcut.matches(
                        tauri_plugin_global_shortcut::Modifiers::CONTROL
                            | tauri_plugin_global_shortcut::Modifiers::SHIFT,
                        tauri_plugin_global_shortcut::Code::Escape,
                    ) && event.state() == ShortcutState::Pressed
                    {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.emit("emergency-pause", ());
                        }
                    }
                })
                .build(),
        )
        .manage(voice::VoiceBridge::default())
        .invoke_handler(tauri::generate_handler![
            voice::voice_provider_info,
            voice::voice_connect,
            voice::voice_send_audio,
            voice::voice_speak,
            voice::voice_audio_stream_end,
            voice::voice_disconnect,
            desktop::show_native_notification,
            desktop::minimize_vyom_window,
            desktop::restore_vyom_window,
        ])
        .setup(|app| {
            if app.get_webview_window("main").is_none() {
                tauri::WebviewWindowBuilder::from_config(
                    app.handle(),
                    &app.config().app.windows[0],
                )?
                .build()?;
            }
            brain::ensure_brain_running(std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")));
            desktop::install_tray(app)?;
            desktop::install_close_to_tray(app);
            #[cfg(desktop)]
            {
                use tauri_plugin_global_shortcut::GlobalShortcutExt;
                let _ = app.global_shortcut().register(EMERGENCY_PAUSE_SHORTCUT);
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running VYOM");
}

#[cfg(test)]
mod tests {
    use super::install_tls_crypto_provider;

    #[test]
    fn installs_rustls_crypto_provider_before_tls_configuration() {
        install_tls_crypto_provider();

        assert!(rustls::crypto::CryptoProvider::get_default().is_some());
        let _ = rustls::ClientConfig::builder();
    }
}
