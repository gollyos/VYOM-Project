#!/usr/bin/env bash
# Prepares the self-contained runtimes VYOM's installer bundles, so a
# fresh Windows PC needs NEITHER a system Python NOR a system Node.js
# to run VYOM after installing it. Run this once before `npm run
# desktop:build` (or whenever PYTHON_VERSION/NODE_VERSION below
# change) - the output lands in src-tauri/bundled/, which
# tauri.conf.json's bundle.resources copies into the installer.
#
# This directory is gitignored (large binaries) - every dev machine
# regenerates it locally from these pinned, verifiable upstream URLs
# rather than committing ~330MB of binaries to the repo.
set -euo pipefail

PYTHON_VERSION="3.11.9"
NODE_VERSION="22.14.0"

cd "$(dirname "$0")/.."
BUNDLED_DIR="src-tauri/bundled"
BRAIN_DIR="services/brain"

echo "== VYOM bundled runtime prep =="
mkdir -p "$BUNDLED_DIR"

# -- Python (embeddable, official python.org distribution) ------------------
if [ ! -x "$BUNDLED_DIR/python-runtime/python.exe" ]; then
  echo "-- Downloading Python $PYTHON_VERSION embeddable..."
  curl -sL -o "$BUNDLED_DIR/python-embed.zip" \
    "https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-embed-amd64.zip"
  mkdir -p "$BUNDLED_DIR/python-runtime"
  (cd "$BUNDLED_DIR/python-runtime" && unzip -oq ../python-embed.zip)
  rm -f "$BUNDLED_DIR/python-embed.zip"

  # Embeddable Python ships with pip DISABLED and no cwd on sys.path by
  # default - enable both. `import site` + Lib\site-packages is what
  # makes `pip install --target` packages importable at all; without
  # this every dependency installs but nothing can import it.
  PTH_FILE=$(ls "$BUNDLED_DIR"/python-runtime/python3*._pth)
  cat > "$PTH_FILE" <<'EOF'
python311.zip
.
Lib\site-packages

import site
EOF

  echo "-- Bootstrapping pip..."
  curl -sL -o "$BUNDLED_DIR/python-runtime/get-pip.py" "https://bootstrap.pypa.io/get-pip.py"
  "$BUNDLED_DIR/python-runtime/python.exe" "$BUNDLED_DIR/python-runtime/get-pip.py" --no-warn-script-location
  rm -f "$BUNDLED_DIR/python-runtime/get-pip.py"
else
  echo "-- Python runtime already present, skipping download"
fi

echo "-- Installing Brain's pinned dependencies into the embedded runtime..."
# Reads pyproject.toml's [project.dependencies] the same install would
# use, plus the optional-dependency groups actually used at runtime
# (artifacts/media/desktop extras) - kept as an explicit list here
# rather than `pip install .` because embeddable Python cannot build
# an editable/local install of the app package itself; app/ is copied
# in as a resource, not pip-installed.
"$BUNDLED_DIR/python-runtime/python.exe" -m pip install --no-warn-script-location \
  "aiosqlite>=0.20,<1" "fastapi>=0.116,<1" "httpx>=0.28,<1" "pydantic>=2.11,<3" \
  "python-dotenv>=1.1,<2" "PyYAML>=6.0,<7" "playwright>=1.55,<2" "Pillow>=11,<12" \
  "uvicorn[standard]>=0.35,<1" "tzdata>=2025.1" "psutil>=6.0,<7" "pyperclip>=1.9,<2" \
  "pywinauto>=0.6.9,<0.7" "pygetwindow>=0.0.9,<1" "pywin32>=306" "screeninfo>=0.8,<1" \
  "qrcode[pil]>=7.4,<8" "edge-tts>=7.0,<8" "python-docx>=1.1,<2" "openpyxl>=3.1,<4" \
  "python-pptx>=1.0,<2" "pymupdf>=1.28,<2" "pyautogui>=0.9.54,<1"

echo "-- Trimming the Python runtime (pycache, docs)..."
find "$BUNDLED_DIR/python-runtime" -iname "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$BUNDLED_DIR/python-runtime/Lib/site-packages" -iname "*.chm" -delete 2>/dev/null || true
find "$BUNDLED_DIR/python-runtime" -iname "*.pyc" -delete 2>/dev/null || true

echo "-- Verifying the Brain actually boots with the bundled runtime..."
# NOTE: plain `python -c "import app.main"` fails here even with cwd
# set - embeddable Python's python3xx._pth disables environment-based
# sys.path configuration entirely (PYTHONPATH is ignored), and a bare
# `-m app.main` does not add cwd either. What actually works at
# runtime (and what brain.rs spawns) is `python -m uvicorn
# app.main:app` specifically - uvicorn's own app-import machinery adds
# the current working directory to sys.path itself. Verify with the
# REAL invocation: boot it briefly, confirm /health responds, then
# stop it.
(
  cd "$BRAIN_DIR"
  "../../$BUNDLED_DIR/python-runtime/python.exe" -m uvicorn app.main:app \
    --host 127.0.0.1 --port 58211 > /tmp/vyom-bundle-verify.log 2>&1 &
  UVICORN_PID=$!
  for _ in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:58211/health" > /dev/null 2>&1; then
      kill "$UVICORN_PID" 2>/dev/null || true
      exit 0
    fi
    sleep 1
  done
  kill "$UVICORN_PID" 2>/dev/null || true
  echo "   Brain did not report healthy within 30s - see /tmp/vyom-bundle-verify.log"
  cat /tmp/vyom-bundle-verify.log
  exit 1
) && echo "   OK" || { echo "   FAILED - the Brain does not boot with the bundled Python"; exit 1; }

# -- Node.js (portable, official nodejs.org distribution) -------------------
NEED_NPM_INSTALL=0
if [ ! -x "$BUNDLED_DIR/node-runtime/node.exe" ]; then
  echo "-- Downloading Node.js $NODE_VERSION..."
  curl -sL -o "$BUNDLED_DIR/node-win.zip" \
    "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-win-x64.zip"
  (cd "$BUNDLED_DIR" && unzip -oq node-win.zip && rm -rf node-runtime && mv "node-v${NODE_VERSION}-win-x64" node-runtime)
  rm -f "$BUNDLED_DIR/node-win.zip"
  NEED_NPM_INSTALL=1
else
  echo "-- Node runtime already present, skipping download"
fi

if [ ! -d "$BRAIN_DIR/whatsapp_connector/node_modules" ] || [ "$NEED_NPM_INSTALL" = "1" ]; then
  echo "-- Installing WhatsApp connector's npm dependencies (bundled node)..."
  # npm.cmd lives at node-runtime/node_modules/npm - must run BEFORE
  # the node_modules strip below, or `npm install` itself breaks
  # (npm is implemented as a Node package, not a standalone binary).
  (cd "$BRAIN_DIR/whatsapp_connector" && "../../../$BUNDLED_DIR/node-runtime/npm.cmd" install --omit=dev)
else
  echo "-- whatsapp_connector/node_modules already present, skipping npm install"
fi

if [ "$NEED_NPM_INSTALL" = "1" ]; then
  # Only node.exe itself is spawned at runtime (connector.js is run
  # directly, never through npm/npx) - strip everything else, INCLUDING
  # npm's own node_modules, to keep the installer smaller. This must
  # run AFTER the npm install above, never before.
  rm -rf "$BUNDLED_DIR/node-runtime/node_modules" \
         "$BUNDLED_DIR/node-runtime"/corepack* \
         "$BUNDLED_DIR/node-runtime/install_tools.bat" \
         "$BUNDLED_DIR/node-runtime/nodevars.bat" \
         "$BUNDLED_DIR/node-runtime/CHANGELOG.md"
fi

echo "-- Verifying whatsapp-web.js loads with the bundled node.exe..."
(cd "$BRAIN_DIR/whatsapp_connector" && "../../../$BUNDLED_DIR/node-runtime/node.exe" -e "require('whatsapp-web.js')") \
  && echo "   OK" || { echo "   FAILED - whatsapp-web.js does not load with the bundled Node"; exit 1; }

PYTHON_SIZE=$(du -sh "$BUNDLED_DIR/python-runtime" | cut -f1)
NODE_SIZE=$(du -sh "$BUNDLED_DIR/node-runtime" | cut -f1)
echo ""
echo "== Done =="
echo "   Python runtime: $PYTHON_SIZE ($BUNDLED_DIR/python-runtime)"
echo "   Node runtime:   $NODE_SIZE ($BUNDLED_DIR/node-runtime)"
echo "   Run 'npm run desktop:build' to produce the installer with these bundled."
