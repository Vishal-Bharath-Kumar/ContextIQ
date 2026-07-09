#!/usr/bin/env bash
# =============================================================================
# diagram.sh — IDE-agnostic local diagram renderer
# Works in: Windsurf, VS Code, Cursor, Zed, terminal, CI/CD pipelines
#
# Usage:
#   ./bin/diagram.sh <file.puml|file.mmd>        render single file (PNG)
#   ./bin/diagram.sh <file> --svg                render as SVG
#   ./bin/diagram.sh --all                       render all in ./diagrams/
#   ./bin/diagram.sh --all --svg                 render all as SVG
#   ./bin/diagram.sh --watch                     watch ./diagrams/ and auto-render
#   ./bin/diagram.sh --watch --dir src/          watch a custom directory
#   ./bin/diagram.sh --server                    start PlantUML local HTTP server
#   ./bin/diagram.sh --server --stop             stop PlantUML server
#   ./bin/diagram.sh --check                     verify all dependencies
#   ./bin/diagram.sh --help                      show this help
# =============================================================================

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
PLANTUML_JAR="${PLANTUML_JAR:-$HOME/plantuml.jar}"
PLANTUML_SERVER="${PLANTUML_SERVER:-http://localhost:8080}"
PLANTUML_PORT="${PLANTUML_PORT:-8080}"
DIAGRAMS_DIR="${DIAGRAMS_DIR:-diagrams}"
PID_FILE=".plantuml_server.pid"
FORMAT="png"
WATCH_DIR="$DIAGRAMS_DIR"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

ok()   { echo -e "${GREEN}  ✅ $*${NC}"; }
err()  { echo -e "${RED}  ❌ $*${NC}"; }
warn() { echo -e "${YELLOW}  ⚠️  $*${NC}"; }
info() { echo -e "${CYAN}  ℹ️  $*${NC}"; }
step() { echo -e "${BLUE}▶ $*${NC}"; }

# ── Helpers ───────────────────────────────────────────────────────────────────
check_java() {
    if ! command -v java &>/dev/null; then
        err "Java not found — install from https://adoptium.net"
        return 1
    fi
    ok "Java: $(java -version 2>&1 | head -1)"
}

check_plantuml_jar() {
    if [[ ! -f "$PLANTUML_JAR" ]]; then
        err "plantuml.jar not found at: $PLANTUML_JAR"
        echo "    → Download: https://plantuml.com/download"
        echo "    → Or set:   export PLANTUML_JAR=/path/to/plantuml.jar"
        return 1
    fi
    ok "plantuml.jar: $PLANTUML_JAR"
}

check_mmdc() {
    if ! command -v mmdc &>/dev/null; then
        err "mmdc not found — run: npm install -g @mermaid-js/mermaid-cli"
        return 1
    fi
    ok "mmdc: $(mmdc --version 2>/dev/null || echo 'found')"
}

check_server() {
    if curl -s --max-time 2 "$PLANTUML_SERVER" &>/dev/null; then
        ok "PlantUML server: running at $PLANTUML_SERVER"
        return 0
    fi
    warn "PlantUML server: not running (jar fallback will be used)"
    echo "    → Start: $0 --server"
    return 1
}

server_running() {
    curl -s --max-time 2 "$PLANTUML_SERVER" &>/dev/null
}

# ── PlantUML encoding (pure bash) ─────────────────────────────────────────────
# Used to call the local HTTP server without Python
encode_plantuml_via_python() {
    local text="$1"
    python3 - "$text" <<'PYEOF'
import sys, zlib
text = open(sys.argv[1]).read() if len(sys.argv) > 1 and sys.argv[1] != '-' else sys.stdin.read()
CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
data = zlib.compress(text.encode("utf-8"))[2:-4]
result = []
for i in range(0, len(data), 3):
    chunk = data[i:i+3]
    b = (chunk[0]<<16)+((chunk[1] if len(chunk)>1 else 0)<<8)+(chunk[2] if len(chunk)>2 else 0)
    result+=[CHARS[(b>>18)&63],CHARS[(b>>12)&63],
             CHARS[(b>>6)&63] if len(chunk)>1 else "=",
             CHARS[b&63] if len(chunk)>2 else "="]
print("".join(result))
PYEOF
}

# ── Render single PlantUML file ───────────────────────────────────────────────
render_plantuml() {
    local src="$1"
    local fmt="$2"
    local out="${src%.*}.${fmt}"

    # Try server first
    if server_running && command -v python3 &>/dev/null; then
        local encoded
        encoded=$(python3 - <<PYEOF
import sys, zlib
text = open("$src").read()
CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
data = zlib.compress(text.encode("utf-8"))[2:-4]
result = []
for i in range(0, len(data), 3):
    chunk = data[i:i+3]
    b = (chunk[0]<<16)+((chunk[1] if len(chunk)>1 else 0)<<8)+(chunk[2] if len(chunk)>2 else 0)
    result+=[CHARS[(b>>18)&63],CHARS[(b>>12)&63],
             CHARS[(b>>6)&63] if len(chunk)>1 else "=",
             CHARS[b&63] if len(chunk)>2 else "="]
print("".join(result))
PYEOF
)
        local url="$PLANTUML_SERVER/plantuml/${fmt}/${encoded}"
        if curl -s --max-time 10 -o "$out" "$url"; then
            ok "[server] $(basename "$src") → $(basename "$out")"
            return 0
        fi
        warn "Server render failed — falling back to jar"
    fi

    # Fallback: java -jar
    if [[ ! -f "$PLANTUML_JAR" ]]; then
        err "plantuml.jar not found. Run: $0 --check"
        return 1
    fi
    local flag="-tpng"
    [[ "$fmt" == "svg" ]] && flag="-tsvg"
    if java -jar "$PLANTUML_JAR" "$flag" "$src" 2>/dev/null; then
        ok "[jar]    $(basename "$src") → $(basename "$out")"
    else
        err "PlantUML render failed: $src"
        return 1
    fi
}

# ── Render single Mermaid file ────────────────────────────────────────────────
render_mermaid() {
    local src="$1"
    local fmt="$2"
    local out="${src%.*}.${fmt}"

    if ! command -v mmdc &>/dev/null; then
        err "mmdc not found. Run: npm install -g @mermaid-js/mermaid-cli"
        return 1
    fi
    if mmdc -i "$src" -o "$out" -b white --quiet 2>/dev/null; then
        ok "[mmdc]   $(basename "$src") → $(basename "$out")"
    else
        err "Mermaid render failed: $src"
        return 1
    fi
}

# ── Render dispatcher ─────────────────────────────────────────────────────────
render_file() {
    local src="$1"
    local fmt="${2:-png}"

    if [[ ! -f "$src" ]]; then
        err "File not found: $src"
        return 1
    fi

    local ext="${src##*.}"
    case "${ext,,}" in
        puml|plantuml) render_plantuml "$src" "$fmt" ;;
        mmd|mermaid)   render_mermaid  "$src" "$fmt" ;;
        *)             warn "Skipping unsupported extension: .$ext" ;;
    esac
}

# ── Render all files in a directory ──────────────────────────────────────────
render_all() {
    local dir="$1"
    local fmt="$2"

    if [[ ! -d "$dir" ]]; then
        err "Directory not found: $dir"
        exit 1
    fi

    local files=()
    while IFS= read -r -d '' f; do
        files+=("$f")
    done < <(find "$dir" \( -name "*.puml" -o -name "*.plantuml" -o -name "*.mmd" -o -name "*.mermaid" \) -print0 2>/dev/null)

    if [[ ${#files[@]} -eq 0 ]]; then
        warn "No diagram files found in: $dir"
        exit 0
    fi

    step "Rendering ${#files[@]} diagram(s) in $dir ..."
    echo ""
    local ok_count=0 fail_count=0
    for f in "${files[@]}"; do
        if render_file "$f" "$fmt"; then
            ((ok_count++)) || true
        else
            ((fail_count++)) || true
        fi
    done

    echo ""
    echo "─────────────────────────────────"
    ok "Done — $ok_count rendered"
    [[ $fail_count -gt 0 ]] && err "$fail_count failed"
}

# ── File watcher (requires inotifywait on Linux, fswatch on macOS) ─────────────
watch_diagrams() {
    local dir="$1"
    local fmt="$2"

    if [[ ! -d "$dir" ]]; then
        mkdir -p "$dir"
        info "Created watch directory: $dir"
    fi

    step "Watching: $(realpath "$dir")"
    info "Format : ${fmt^^}"
    info "Ctrl+C : Stop watcher"
    echo ""

    # macOS: use fswatch; Linux: use inotifywait; fallback: polling loop
    if command -v fswatch &>/dev/null; then
        fswatch -0 --event Modified --event Created "$dir" | while IFS= read -r -d '' file; do
            local ext="${file##*.}"
            case "${ext,,}" in
                puml|plantuml|mmd|mermaid)
                    echo ""
                    step "Changed: $(basename "$file")"
                    render_file "$file" "$fmt"
                    ;;
            esac
        done
    elif command -v inotifywait &>/dev/null; then
        inotifywait -m -r -e close_write,moved_to "$dir" --format '%w%f' 2>/dev/null | while read -r file; do
            local ext="${file##*.}"
            case "${ext,,}" in
                puml|plantuml|mmd|mermaid)
                    echo ""
                    step "Changed: $(basename "$file")"
                    render_file "$file" "$fmt"
                    ;;
            esac
        done
    else
        # Polling fallback — works everywhere
        warn "inotifywait/fswatch not found — using 2s polling fallback"
        echo "  → Install inotifywait (Linux): sudo apt install inotify-tools"
        echo "  → Install fswatch (macOS):     brew install fswatch"
        echo ""
        declare -A last_modified
        while true; do
            while IFS= read -r -d '' file; do
                local mtime
                mtime=$(stat -c %Y "$file" 2>/dev/null || stat -f %m "$file" 2>/dev/null || echo 0)
                local prev="${last_modified[$file]:-0}"
                if [[ "$mtime" != "$prev" ]]; then
                    last_modified["$file"]="$mtime"
                    if [[ "$prev" != "0" ]]; then
                        echo ""
                        step "Changed: $(basename "$file")"
                        render_file "$file" "$fmt"
                    fi
                fi
            done < <(find "$dir" \( -name "*.puml" -o -name "*.plantuml" -o -name "*.mmd" -o -name "*.mermaid" \) -print0 2>/dev/null)
            sleep 2
        done
    fi
}

# ── PlantUML server management ────────────────────────────────────────────────
server_start() {
    if server_running; then
        ok "PlantUML server already running at $PLANTUML_SERVER"
        return 0
    fi
    if [[ ! -f "$PLANTUML_JAR" ]]; then
        err "plantuml.jar not found: $PLANTUML_JAR"
        exit 1
    fi
    step "Starting PlantUML server on port $PLANTUML_PORT ..."
    java -jar "$PLANTUML_JAR" "-picoweb:$PLANTUML_PORT" &>/dev/null &
    local pid=$!
    echo "$pid" > "$PID_FILE"

    for i in $(seq 1 16); do
        sleep 0.5
        if server_running; then
            ok "Server ready at $PLANTUML_SERVER  (PID: $pid)"
            info "Stop with: $0 --server --stop"
            return 0
        fi
        printf "  Waiting... (%.1fs)\r" "$(echo "scale=1; $i * 0.5" | bc)"
    done

    err "Server did not start. Check Java installation."
    kill "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    exit 1
}

server_stop() {
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE")
        kill "$pid" 2>/dev/null && ok "PlantUML server stopped (PID: $pid)" || warn "Process $pid not found"
        rm -f "$PID_FILE"
    else
        warn "No PID file found — server may not be running"
    fi
}

# ── Dependency check ──────────────────────────────────────────────────────────
check_all() {
    echo ""
    step "Checking dependencies ..."
    echo ""
    check_java        || true
    check_plantuml_jar || true
    check_server      || true
    check_mmdc        || true
    echo ""
}

# ── Help ──────────────────────────────────────────────────────────────────────
show_help() {
    echo ""
    echo "  diagram.sh — local diagram renderer (PlantUML + Mermaid)"
    echo ""
    echo "  Usage:"
    echo "    ./bin/diagram.sh <file.puml>          render single PlantUML file"
    echo "    ./bin/diagram.sh <file.mmd>           render single Mermaid file"
    echo "    ./bin/diagram.sh <file> --svg         render as SVG"
    echo "    ./bin/diagram.sh --all                render all in ./diagrams/"
    echo "    ./bin/diagram.sh --all --svg          render all as SVG"
    echo "    ./bin/diagram.sh --all --dir src/     render all in custom folder"
    echo "    ./bin/diagram.sh --watch              auto-render on file save"
    echo "    ./bin/diagram.sh --watch --dir src/   watch custom folder"
    echo "    ./bin/diagram.sh --server             start PlantUML HTTP server"
    echo "    ./bin/diagram.sh --server --stop      stop PlantUML server"
    echo "    ./bin/diagram.sh --check              verify all dependencies"
    echo ""
    echo "  Environment variables:"
    echo "    PLANTUML_JAR     path to plantuml.jar  (default: ~/plantuml.jar)"
    echo "    PLANTUML_PORT    server port            (default: 8080)"
    echo "    DIAGRAMS_DIR     default diagram folder (default: ./diagrams)"
    echo ""
}

# ── Argument parsing ──────────────────────────────────────────────────────────
CMD=""
FILE=""
STOP=false

for arg in "$@"; do
    case "$arg" in
        --svg)       FORMAT="svg" ;;
        --all)       CMD="all" ;;
        --watch)     CMD="watch" ;;
        --server)    CMD="server" ;;
        --check)     CMD="check" ;;
        --help|-h)   CMD="help" ;;
        --stop)      STOP=true ;;
        --dir=*)     WATCH_DIR="${arg#--dir=}" ;;
        --dir)       : ;;   # handled by next arg — see below
        *)
            # If previous was --dir, this is the value
            if [[ "${prev_arg:-}" == "--dir" ]]; then
                WATCH_DIR="$arg"
            elif [[ -z "$CMD" && "$arg" != --* ]]; then
                FILE="$arg"
                CMD="single"
            fi
            ;;
    esac
    prev_arg="$arg"
done

# ── Dispatch ──────────────────────────────────────────────────────────────────
case "$CMD" in
    single)  render_file "$FILE" "$FORMAT" ;;
    all)     render_all "$WATCH_DIR" "$FORMAT" ;;
    watch)   watch_diagrams "$WATCH_DIR" "$FORMAT" ;;
    server)  $STOP && server_stop || server_start ;;
    check)   check_all ;;
    help|"") show_help ;;
esac
