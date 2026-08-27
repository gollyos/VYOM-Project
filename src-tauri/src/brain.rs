use std::path::{Path, PathBuf};
use std::time::Duration;

use tauri::path::BaseDirectory;
use tauri::{AppHandle, Manager};
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
///
/// Two ways to find a working Python, tried in order:
/// 1. The BUNDLED embedded runtime shipped inside the installed app's own
///    resource directory (resources/runtime/python/python.exe) - this is
///    what makes VYOM work on a machine with no system Python installed
///    at all, which is the whole point of shipping an installer.
/// 2. `python`/`python3` on PATH - the dev-mode fallback, so a developer
///    running `npm run desktop:dev` without ever running
///    scripts/prepare-bundled-runtimes.sh still gets a working Brain.
pub fn ensure_brain_running(app: &AppHandle, manifest_dir: PathBuf) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        if is_listening(BRAIN_HOST, BRAIN_PORT).await {
            return; // already running (started manually, or a prior launch)
        }
        let brain_dir = resolve_brain_dir(&app, &manifest_dir);
        if !brain_dir.is_dir() {
            eprintln!("VYOM: Brain source directory not found at {brain_dir:?}; not starting the Brain automatically");
            return;
        }
        // Whether brain_dir came from the bundled resource layout
        // (resources/brain/) vs. the dev checkout (services/brain/) -
        // ONLY the bundled layout needs the PROJECT_ROOT-relative env
        // overrides in try_spawn, because config.py's own
        // parents[4]-based arithmetic already resolves correctly for
        // the dev checkout's fixed nesting depth. Applying the
        // overrides unconditionally would break dev mode instead
        // (brain_dir.parent() there is services/, not the repo root).
        let is_bundled_layout = app
            .path()
            .resolve("brain", BaseDirectory::Resource)
            .map(|resource_brain| resource_brain == brain_dir)
            .unwrap_or(false);

        if let Some(bundled_python) = resolve_bundled_python(&app) {
            if try_spawn(&bundled_python, &brain_dir, resolve_bundled_node(&app).as_deref(), is_bundled_layout).is_ok() {
                return;
            }
            eprintln!("VYOM: bundled Python at {bundled_python:?} failed to start the Brain; falling back to PATH");
        }
        for python in ["python", "python3"] {
            if try_spawn(Path::new(python), &brain_dir, resolve_bundled_node(&app).as_deref(), is_bundled_layout).is_ok() {
                return;
            }
        }
        eprintln!("VYOM: could not start the Brain automatically (no working Python interpreter found, bundled or on PATH); start it manually with `python -m uvicorn app.main:app --host 127.0.0.1 --port 7788` from services/brain");
    });
}

/// The installed app ships services/brain/app as a bundled resource
/// (see tauri.conf.json bundle.resources) so the Brain's source runs
/// from inside the install directory, not a dev checkout that may not
/// exist on the end user's machine. Dev builds (`npm run desktop:dev`)
/// have no resource bundle at all - resolve() fails there, and this
/// falls back to the real source tree next to src-tauri/ instead.
fn resolve_brain_dir(app: &AppHandle, manifest_dir: &Path) -> PathBuf {
    if let Ok(resource_brain) = app.path().resolve("brain", BaseDirectory::Resource) {
        if resource_brain.join("app").is_dir() {
            return resource_brain;
        }
    }
    manifest_dir.join("../services/brain")
}

/// Same resolve-or-fall-back pattern for the bundled Python runtime.
/// Returns None (not a PATH fallback) when the resource plainly is not
/// there, so the caller can log that it is using the PATH fallback for
/// a REASON rather than silently trying a path that will just fail.
fn resolve_bundled_python(app: &AppHandle) -> Option<PathBuf> {
    let candidate = app
        .path()
        .resolve("runtime/python/python.exe", BaseDirectory::Resource)
        .ok()?;
    candidate.is_file().then_some(candidate)
}

/// The bundled portable Node.js runtime, passed to the Brain as
/// VYOM_NODE_BIN (see app/main.py's WhatsAppConnector construction) so
/// the WhatsApp connector child process it spawns uses the SAME
/// no-system-Node-required runtime as everything else, instead of
/// falling back to "node" on PATH (which a fresh install has no
/// reason to have).
fn resolve_bundled_node(app: &AppHandle) -> Option<PathBuf> {
    let candidate = app
        .path()
        .resolve("runtime/node/node.exe", BaseDirectory::Resource)
        .ok()?;
    candidate.is_file().then_some(candidate)
}

fn bundled_external_capabilities_config(project_root: &Path) -> PathBuf {
    project_root.join("config").join("external_capabilities.yaml")
}

async fn is_listening(host: &str, port: u16) -> bool {
    tokio::time::timeout(CONNECT_TIMEOUT, TcpStream::connect((host, port)))
        .await
        .map(|result| result.is_ok())
        .unwrap_or(false)
}

fn try_spawn(python: &Path, brain_dir: &PathBuf, bundled_node: Option<&Path>, is_bundled: bool) -> std::io::Result<()> {
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
    if let Some(node) = bundled_node {
        command.env("VYOM_NODE_BIN", node);
    }
    // app/core/config.py derives PROJECT_ROOT by counting parent
    // directories up from its OWN file location
    // (Path(__file__).parents[4]) - a fragile assumption that only
    // holds for the dev checkout's fixed nesting depth
    // (services/brain/app/core/config.py -> repo root). The bundled
    // resource layout nests one level shallower
    // (resources/brain/app/core/config.py), so that arithmetic would
    // silently resolve PROJECT_ROOT to the wrong directory and every
    // config/*.yaml load would fail. Rather than special-case the
    // Python arithmetic for two different layouts, set the explicit
    // env override every one of those paths already supports (see
    // config.py's os.getenv(...) defaults) directly from the ONE place
    // that genuinely knows where the resource bundle landed - ONLY
    // when actually running the bundled layout (see is_bundled_layout
    // at the call site: unconditionally doing this would break dev
    // mode, where brain_dir.parent() is services/, not the repo root).
    if is_bundled {
        if let Some(project_root) = brain_dir.parent() {
            let config_dir = project_root.join("config");
            let data_root = project_root.join("data");
            command
                .env("VYOM_MODEL_REGISTRY", config_dir.join("models.yaml"))
                .env("VYOM_TOOL_REGISTRY", config_dir.join("tools.yaml"))
                .env("VYOM_MEMORY_CONFIG", config_dir.join("memory.yaml"))
                .env("VYOM_AGENT_CONFIG", config_dir.join("agents.yaml"))
                .env("VYOM_INTEGRATION_CONFIG", config_dir.join("integrations.yaml"))
                .env("VYOM_AUTOMATION_CONFIG", config_dir.join("automations.yaml"))
                .env("VYOM_RESEARCH_CONFIG", config_dir.join("research.yaml"))
                .env(
                    "VYOM_EXTERNAL_CAPABILITIES_CONFIG",
                    bundled_external_capabilities_config(project_root),
                )
                .env("VYOM_ARTIFACTS_ROOT", data_root.join("artifacts"))
                .env("VYOM_SKILLS_ROOT", data_root.join("skills"))
                .env("VYOM_AGENTS_ROOT", data_root.join("agents"))
                .env("VYOM_BACKUP_ROOT", data_root.join("backups"))
                .env("VYOM_ALLOWED_ROOTS", project_root);
        }
    }
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
    use std::path::Path;

    use super::{bundled_external_capabilities_config, is_listening};
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

    #[test]
    fn bundled_external_capabilities_path_stays_inside_installed_config() {
        let root = Path::new("C:/Users/example/AppData/Local/VYOM");
        assert_eq!(
            bundled_external_capabilities_config(root),
            root.join("config").join("external_capabilities.yaml"),
        );
    }
}
