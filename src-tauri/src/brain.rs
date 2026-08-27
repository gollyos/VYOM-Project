use std::fs::OpenOptions;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicI64, AtomicU32, Ordering};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use tauri::path::BaseDirectory;
use tauri::{AppHandle, Manager};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio::process::Command;

const BRAIN_HOST: &str = "127.0.0.1";
const BRAIN_PORT: u16 = 7788;
const CONNECT_TIMEOUT: Duration = Duration::from_millis(400);
const HEALTH_TIMEOUT: Duration = Duration::from_secs(3);
/// The Brain's lifespan init (registries, MCP, engines) can take well over a
/// minute on a cold start; uvicorn binds the port long before it answers
/// HTTP, so readiness must be a health poll, not a TCP probe.
const READY_WAIT: Duration = Duration::from_secs(150);
const READY_POLL_INTERVAL: Duration = Duration::from_secs(2);
const SUPERVISOR_INTERVAL: Duration = Duration::from_secs(15);
const SUPERVISOR_FAILURE_STREAK: u32 = 2;
/// Bounded supervisor: after this many respawns inside the window we stop
/// touching the port and just keep logging, so a crash-looping Brain can
/// never turn into a process-spawning loop.
const MAX_RESPAWNS_PER_WINDOW: u32 = 5;
const RESPAWN_WINDOW: Duration = Duration::from_secs(10 * 60);

static RESPAWN_WINDOW_START_MS: AtomicI64 = AtomicI64::new(0);
static RESPAWN_COUNT: AtomicU32 = AtomicU32::new(0);

/// PC-on primary behavior: if the Brain is not already healthy, start it as
/// a local subprocess so VYOM works standalone on a fresh boot/login, and
/// KEEP it alive. This used to be a fire-and-forget spawn whose crash was
/// invisible (stdio nulled, no readiness check, no restart) - the 2026-08-27
/// installed build died at import with a SyntaxError and the desktop app sat
/// on "VYOM Brain disconnected" forever, which is why it is now a BOUNDED
/// supervisor:
///
/// 1. Spawn output goes to `<brain>/data/logs/brain-spawn.log` - crashes are
///    diagnosable instead of silent.
/// 2. After spawning we poll `/health` (TCP connect succeeds long before the
///    HTTP server answers, so a port probe proves nothing).
/// 3. A background loop health-checks every 15s; after a failure streak it
///    reclaims the port from python processes only, respawns (max 5 per 10
///    minutes) and waits for readiness again. A healthy manually-started
///    dev Brain is never touched.
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
        if brain_health_ok().await {
            start_supervisor(app, manifest_dir);
            return; // already running and healthy (started manually, or a prior launch)
        }
        // Something holds the port: either a Brain still booting (uvicorn
        // binds before serving) or a hung/zombie listener. Give a booting
        // Brain its full startup budget before reclaiming anything.
        if is_listening(BRAIN_HOST, BRAIN_PORT).await {
            wait_ready(READY_WAIT).await;
            if brain_health_ok().await {
                start_supervisor(app, manifest_dir);
                return;
            }
            let reclaimed = kill_port_holders(BRAIN_PORT).await;
            eprintln!("VYOM: port {BRAIN_PORT} was held by an unhealthy listener; reclaimed {reclaimed} python process(es)");
        }
        if spawn_brain(&app, &manifest_dir).await {
            wait_ready(READY_WAIT).await;
        }
        start_supervisor(app, manifest_dir);
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

/// Minimal HTTP `GET /health` over a raw TcpStream - deliberately no HTTP
/// client dependency. Any "HTTP/1.x 200" status line counts as healthy.
async fn brain_health_ok() -> bool {
    let mut stream = match TcpStream::connect((BRAIN_HOST, BRAIN_PORT)).await {
        Ok(stream) => stream,
        Err(_) => return false,
    };
    let request = format!(
        "GET /health HTTP/1.1\r\nHost: {BRAIN_HOST}:{BRAIN_PORT}\r\nConnection: close\r\n\r\n"
    );
    let wrote = tokio::time::timeout(HEALTH_TIMEOUT, stream.write_all(request.as_bytes())).await;
    if wrote.is_err() {
        return false;
    }
    let mut response = Vec::with_capacity(512);
    match tokio::time::timeout(HEALTH_TIMEOUT, stream.read_to_end(&mut response)).await {
        Ok(Ok(_)) => status_line_is_200(&response),
        _ => false,
    }
}

fn status_line_is_200(response: &[u8]) -> bool {
    let text = String::from_utf8_lossy(response);
    match text.find("\r\n") {
        Some(line_end) => {
            let status_line = &text[..line_end];
            status_line.starts_with("HTTP/1.") && status_line.contains(" 200 ")
        }
        None => false,
    }
}

/// Poll `/health` until it answers or the budget runs out. Safe to call
/// while a Brain is mid-boot (uvicorn accepts TCP but does not serve yet).
async fn wait_ready(budget: Duration) -> bool {
    let deadline = tokio::time::Instant::now() + budget;
    while tokio::time::Instant::now() < deadline {
        if brain_health_ok().await {
            return true;
        }
        tokio::time::sleep(READY_POLL_INTERVAL).await;
    }
    false
}

/// Background keep-alive: health-check every SUPERVISOR_INTERVAL; after
/// SUPERVISOR_FAILURE_STREAK consecutive failures, reclaim the port from
/// python processes and respawn (bounded by MAX_RESPAWNS_PER_WINDOW).
fn start_supervisor(app: AppHandle, manifest_dir: PathBuf) {
    tauri::async_runtime::spawn(async move {
        let mut consecutive_failures: u32 = 0;
        loop {
            tokio::time::sleep(SUPERVISOR_INTERVAL).await;
            if brain_health_ok().await {
                consecutive_failures = 0;
                continue;
            }
            consecutive_failures += 1;
            if consecutive_failures < SUPERVISOR_FAILURE_STREAK {
                continue;
            }
            consecutive_failures = 0;
            if !respawn_budget_available() {
                eprintln!("VYOM: Brain unhealthy but respawn budget exhausted for this window; waiting");
                continue;
            }
            RESPAWN_COUNT.fetch_add(1, Ordering::Relaxed);
            let reclaimed = kill_port_holders(BRAIN_PORT).await;
            eprintln!(
                "VYOM: Brain died (health failed {SUPERVISOR_FAILURE_STREAK}x); reclaimed {reclaimed} process(es), respawning"
            );
            if spawn_brain(&app, &manifest_dir).await {
                wait_ready(READY_WAIT).await;
            }
        }
    });
}

fn respawn_budget_available() -> bool {
    let now_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0);
    let window_start = RESPAWN_WINDOW_START_MS.load(Ordering::Relaxed);
    if window_start == 0
        || now_ms.saturating_sub(window_start) > RESPAWN_WINDOW.as_millis() as i64
    {
        RESPAWN_WINDOW_START_MS.store(now_ms, Ordering::Relaxed);
        RESPAWN_COUNT.store(0, Ordering::Relaxed);
        return true;
    }
    RESPAWN_COUNT.load(Ordering::Relaxed) < MAX_RESPAWNS_PER_WINDOW
}

/// Kill whatever LISTENS on `port`, but only python-family processes - a
/// foreign process squatting on the port is logged, not murdered.
/// Returns how many processes were actually killed.
async fn kill_port_holders(port: u16) -> usize {
    let pids = listening_pids(port).await;
    let mut killed = 0;
    for pid in pids {
        if !is_python_pid(&pid).await {
            eprintln!("VYOM: PID {pid} holds port {port} but is not python; leaving it alone");
            continue;
        }
        let output = Command::new("taskkill")
            .args(["/PID", &pid, "/F"])
            .no_window()
            .output()
            .await;
        match output {
            Ok(status) if status.status.success() => killed += 1,
            _ => eprintln!("VYOM: taskkill /PID {pid} failed"),
        }
    }
    killed
}

/// Extract the LISTENING PIDs for `port` from `netstat -ano -p tcp`.
async fn listening_pids(port: u16) -> Vec<String> {
    let output = match Command::new("netstat")
        .args(["-ano", "-p", "tcp"])
        .no_window()
        .output()
        .await
    {
        Ok(output) if output.status.success() => output,
        _ => return Vec::new(),
    };
    parse_listening_pids(&String::from_utf8_lossy(&output.stdout), port)
}

fn parse_listening_pids(netstat_text: &str, port: u16) -> Vec<String> {
    let port_suffix = format!(":{port}");
    netstat_text
        .lines()
        .filter_map(|line| {
            let cols: Vec<&str> = line.split_whitespace().collect();
            if cols.len() < 5
                || !cols[0].eq_ignore_ascii_case("TCP")
                || !cols[3].eq_ignore_ascii_case("LISTENING")
            {
                return None;
            }
            let local = cols[1];
            let is_port = local
                .rsplit_once(':')
                .map(|(_, p)| p == port_suffix.trim_start_matches(':'))
                .unwrap_or(false);
            is_port.then(|| cols[4].to_string())
        })
        .collect()
}

async fn is_python_pid(pid: &str) -> bool {
    let output = match Command::new("tasklist")
        .args(["/FI", &format!("PID eq {pid}"), "/FO", "CSV", "/NH"])
        .no_window()
        .output()
        .await
    {
        Ok(output) if output.status.success() => output,
        _ => return false,
    };
    let first_field = String::from_utf8_lossy(&output.stdout)
        .lines()
        .next()
        .unwrap_or("")
        .split(',')
        .next()
        .unwrap_or("")
        .trim_matches('"')
        .to_ascii_lowercase();
    first_field.contains("python")
}

async fn spawn_brain(app: &AppHandle, manifest_dir: &Path) -> bool {
        let brain_dir = resolve_brain_dir(app, manifest_dir);
        if !brain_dir.is_dir() {
            eprintln!("VYOM: Brain source directory not found at {brain_dir:?}; not starting the Brain automatically");
            return false;
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

        if let Some(bundled_python) = resolve_bundled_python(app) {
            if try_spawn(&bundled_python, &brain_dir, resolve_bundled_node(app).as_deref(), is_bundled_layout).is_ok() {
                return true;
            }
            eprintln!("VYOM: bundled Python at {bundled_python:?} failed to start the Brain; falling back to PATH");
        }
        for python in ["python", "python3"] {
            if try_spawn(Path::new(python), &brain_dir, resolve_bundled_node(app).as_deref(), is_bundled_layout).is_ok() {
                return true;
            }
        }
        eprintln!("VYOM: could not start the Brain automatically (no working Python interpreter found, bundled or on PATH); start it manually with `python -m uvicorn app.main:app --host 127.0.0.1 --port 7788` from services/brain");
        false
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
        .stdout(spawn_log_stdio(brain_dir))
        .stderr(spawn_log_stdio(brain_dir));
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
    // lifetime; the supervisor reclaims the port and respawns when health
    // fails rather than tracking this handle.
    command.spawn().map(|_child| ())
}

/// Brain subprocess output goes to `<brain>/data/logs/brain-spawn.log` so an
/// import crash (the 2026-08-27 SyntaxError class of failure) leaves a
/// traceback instead of vanishing into Stdio::null().
fn spawn_log_stdio(brain_dir: &Path) -> std::process::Stdio {
    let log_path = brain_dir.join("data").join("logs").join("brain-spawn.log");
    match OpenOptions::new().create(true).append(true).open(&log_path) {
        Ok(file) => std::process::Stdio::from(file),
        Err(err) => {
            eprintln!("VYOM: cannot open {log_path:?} for brain output ({err}); discarding output");
            std::process::Stdio::null()
        }
    }
}

trait NoWindow {
    fn no_window(&mut self) -> &mut Self;
}

#[cfg(windows)]
impl NoWindow for Command {
    fn no_window(&mut self) -> &mut Self {
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        self.creation_flags(CREATE_NO_WINDOW);
        self
    }
}

#[cfg(not(windows))]
impl NoWindow for Command {
    fn no_window(&mut self) -> &mut Self {
        self
    }
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use super::{
        bundled_external_capabilities_config, is_listening, parse_listening_pids,
        respawn_budget_available, status_line_is_200, MAX_RESPAWNS_PER_WINDOW, RESPAWN_COUNT,
    };
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

    #[test]
    fn health_response_requires_200_status_line() {
        assert!(status_line_is_200(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"));
        assert!(!status_line_is_200(b"HTTP/1.1 500 Internal Server Error\r\n\r\n"));
        assert!(!status_line_is_200(b"not-http"));
    }

    #[test]
    fn netstat_parser_extracts_only_listening_pids_for_the_port() {
        let sample = "  TCP    127.0.0.1:7788    0.0.0.0:0    LISTENING    4242\n  \
                      TCP    127.0.0.1:7788    10.0.0.1:9    ESTABLISHED  1111\n  \
                      TCP    127.0.0.1:9999    0.0.0.0:0    LISTENING    5150\n";
        assert_eq!(parse_listening_pids(sample, 7788), vec!["4242".to_string()]);
    }

    #[test]
    fn respawn_budget_is_bounded_inside_a_window() {
        // Force a fresh window so this test is independent of prior state.
        super::RESPAWN_WINDOW_START_MS.store(0, std::sync::atomic::Ordering::Relaxed);
        RESPAWN_COUNT.store(0, std::sync::atomic::Ordering::Relaxed);
        assert!(respawn_budget_available());
        RESPAWN_COUNT.store(MAX_RESPAWNS_PER_WINDOW, std::sync::atomic::Ordering::Relaxed);
        assert!(!respawn_budget_available());
    }
}
