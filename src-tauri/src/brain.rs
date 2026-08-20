use std::path::PathBuf;
use std::time::Duration;

use tokio::net::TcpStream;
use tokio::process::Command;

const BRAIN_HOST: &str = "127.0.0.1";
const BRAIN_PORT: u16 = 7788;
const CONNECT_TIMEOUT: Duration = Duration::from_millis(400);

/// PC-on primary behavior: if the Brain is not already listening (the user
/// did not start it manually, e.g. from a dev terminal), start it as a
/// local subprocess so VYOM works standalone on a fresh boot/login. This
/// checks once at launch - it is not a supervisor/auto-restart loop, so a
/// Brain that later crashes is left to the existing frontend reconnect/
/// health-check path (see brain-client.ts) rather than being respawned
/// automatically, matching the "bounded, never endless" pattern used
/// everywhere else in this codebase.
pub fn ensure_brain_running(manifest_dir: PathBuf) {
    tauri::async_runtime::spawn(async move {
        if is_listening(BRAIN_HOST, BRAIN_PORT).await {
            return; // already running (started manually, or a prior launch)
        }
        let brain_dir = manifest_dir.join("../services/brain");
        if !brain_dir.is_dir() {
            eprintln!("VYOM: services/brain not found at {brain_dir:?}; not starting the Brain automatically");
            return;
        }
        for python in ["python", "python3"] {
            if try_spawn(python, &brain_dir).is_ok() {
                return;
            }
        }
        eprintln!("VYOM: could not start the Brain automatically (no working Python interpreter found on PATH); start it manually with `python -m uvicorn app.main:app --host 127.0.0.1 --port 7788` from services/brain");
    });
}

async fn is_listening(host: &str, port: u16) -> bool {
    tokio::time::timeout(CONNECT_TIMEOUT, TcpStream::connect((host, port)))
        .await
        .map(|result| result.is_ok())
        .unwrap_or(false)
}

fn try_spawn(python: &str, brain_dir: &PathBuf) -> std::io::Result<()> {
    let mut command = Command::new(python);
    command
        .args([
            "-m", "uvicorn", "app.main:app",
            "--host", BRAIN_HOST, "--port", &BRAIN_PORT.to_string(),
        ])
        .current_dir(brain_dir)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null());
    #[cfg(windows)]
    {
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    // Detached on purpose (see module docs): VYOM does not own the Brain's
    // lifetime any more than it would if the user had started it manually
    // in a terminal. Dropping the Child handle here does not kill the
    // process on Windows/Unix.
    command.spawn().map(|_child| ())
}

#[cfg(test)]
mod tests {
    use super::is_listening;
    use tokio::net::TcpListener;

    #[tokio::test]
    async fn detects_nothing_listening_on_a_free_port() {
        // Bind port 0 to let the OS hand back a genuinely free port, then
        // drop the listener immediately so nothing is bound there anymore.
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        drop(listener);

        assert!(!is_listening("127.0.0.1", port).await);
    }

    #[tokio::test]
    async fn detects_a_real_listener() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        // Keep the listener alive for the duration of the check by holding
        // it in a background task.
        let _handle = tokio::spawn(async move {
            let _ = listener.accept().await;
        });

        assert!(is_listening("127.0.0.1", port).await);
    }
}
