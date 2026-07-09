# diagram — IDE-agnostic local diagram renderer
## Zero AI calls · Zero cloud · Works in any IDE or CI pipeline

---

## Three scripts, one job

| Script | Platform | Use when |
|--------|----------|----------|
| `bin/diagram.sh` | Linux / macOS | Windsurf, VS Code, Cursor, Zed, terminal |
| `bin/diagram.ps1` | Windows (PowerShell 5.1+ / PS7) | Windsurf, VS Code, Rider, PowerShell terminal |
| `bin/diagram.cmd` | Windows (CMD / legacy) | CMD prompt, older CI agents |

All three have identical commands — pick one per platform.

---

## Quick start

```bash
# Linux / macOS
chmod +x bin/diagram.sh
./bin/diagram.sh --check                          # verify deps
./bin/diagram.sh diagrams/auth_flow.puml          # render one file
./bin/diagram.sh --all                            # render everything

# Windows PowerShell
.\bin\diagram.ps1 --Check
.\bin\diagram.ps1 diagrams\auth_flow.puml
.\bin\diagram.ps1 --All

# Windows CMD
bin\diagram.cmd --check
bin\diagram.cmd diagrams\auth_flow.puml
bin\diagram.cmd --all
```

---

## Full command reference

```
diagram.sh / diagram.ps1 / diagram.cmd

  <file.puml>              render single PlantUML file → .png
  <file.mmd>               render single Mermaid file  → .png
  <file> --svg             render as SVG instead of PNG

  --all                    render all *.puml / *.mmd in ./diagrams/
  --all --svg              render all as SVG
  --all --dir <path>       render all in a custom directory

  --watch                  auto-render on every file save (./diagrams/)
  --watch --dir <path>     watch a custom directory

  --server                 start PlantUML local HTTP server (port 8080)
  --server --stop          stop the server

  --check                  verify all dependencies (Java, jar, mmdc, server)
  --help                   show usage
```

---

## Prerequisites

### 1. Java JRE 8+ (required for PlantUML)

**Windows:**
```powershell
winget install EclipseAdoptium.Temurin.21.JRE
```
**macOS:**
```bash
brew install temurin
```
**Linux:**
```bash
sudo apt install default-jre
```

### 2. plantuml.jar

```bash
# macOS / Linux
curl -L https://github.com/plantuml/plantuml/releases/latest/download/plantuml.jar \
     -o ~/plantuml.jar

# Windows PowerShell
Invoke-WebRequest https://github.com/plantuml/plantuml/releases/latest/download/plantuml.jar `
     -OutFile "$HOME\plantuml.jar"
```

Set a custom path via environment variable:
```bash
export PLANTUML_JAR=/opt/tools/plantuml.jar        # bash
$env:PLANTUML_JAR = "D:\tools\plantuml.jar"        # PowerShell
set PLANTUML_JAR=D:\tools\plantuml.jar             # CMD
```

### 3. Mermaid CLI (for .mmd files)

```bash
npm install -g @mermaid-js/mermaid-cli
```

> **Windows note:** If you get an execution policy error, run:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

---

## Daily workflow

```bash
# Terminal 1 — start server once per session (3–5x faster than jar)
./bin/diagram.sh --server

# Terminal 2 — optional: auto-render on every save
./bin/diagram.sh --watch

# Work normally — save .puml or .mmd files → images appear automatically
```

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PLANTUML_JAR` | `~/plantuml.jar` | Path to plantuml.jar |
| `PLANTUML_PORT` | `8080` | Local server port |
| `DIAGRAMS_DIR` | `./diagrams` | Default diagram directory for `--all` and `--watch` |

---

## IDE integration (no AI required)

### VS Code / Cursor / Windsurf — terminal task

Add to `.vscode/tasks.json`:
```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Render Diagrams",
      "type": "shell",
      "command": "./bin/diagram.sh --all",
      "windows": { "command": ".\\bin\\diagram.ps1 --All" },
      "group": "build",
      "presentation": { "reveal": "always" }
    },
    {
      "label": "Watch Diagrams",
      "type": "shell",
      "command": "./bin/diagram.sh --watch",
      "windows": { "command": ".\\bin\\diagram.ps1 --Watch" },
      "isBackground": true
    }
  ]
}
```

Trigger with `Ctrl+Shift+B` (default build task).

### Makefile

```makefile
diagrams:
	./bin/diagram.sh --all

diagrams-svg:
	./bin/diagram.sh --all --svg

watch-diagrams:
	./bin/diagram.sh --watch

.PHONY: diagrams diagrams-svg watch-diagrams
```

### Azure DevOps Pipeline

```yaml
- task: Bash@3
  displayName: 'Render diagrams'
  inputs:
    targetType: inline
    script: |
      export PLANTUML_JAR=$(Agent.ToolsDirectory)/plantuml.jar
      curl -sL https://github.com/plantuml/plantuml/releases/latest/download/plantuml.jar \
           -o $PLANTUML_JAR
      npm install -g @mermaid-js/mermaid-cli
      ./bin/diagram.sh --all
```

### GitHub Actions

```yaml
- name: Render diagrams
  run: |
    curl -sL https://github.com/plantuml/plantuml/releases/latest/download/plantuml.jar \
         -o ~/plantuml.jar
    npm install -g @mermaid-js/mermaid-cli
    ./bin/diagram.sh --all
```

---

## Watch behaviour by platform

| Platform | Method | Install |
|----------|--------|---------|
| Linux | `inotifywait` (event-driven) | `sudo apt install inotify-tools` |
| macOS | `fswatch` (event-driven) | `brew install fswatch` |
| Any | polling fallback (2s) | built-in, no install needed |
| Windows PS | `FileSystemWatcher` (event-driven) | built-in |
| Windows CMD | polling loop (2s) | built-in |

---

## File naming convention

```
diagrams/<context>_<seq>_<type>_<title>.<ext>

Examples:
  diagrams/auth_001_sequence_b2c_login.puml
  diagrams/db_002_erd_patient_schema.mmd
  diagrams/infra_003_component_azure_landing_zone.puml
```
