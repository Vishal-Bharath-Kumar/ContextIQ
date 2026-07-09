@echo off
REM =============================================================================
REM diagram.cmd — IDE-agnostic local diagram renderer (Windows)
REM Works in: Windsurf, VS Code, Cursor, PowerShell, CMD, CI/CD pipelines
REM
REM Usage:
REM   diagram.cmd <file.puml|file.mmd>       render single file (PNG)
REM   diagram.cmd <file> --svg               render as SVG
REM   diagram.cmd --all                      render all in .\diagrams\
REM   diagram.cmd --all --svg                render all as SVG
REM   diagram.cmd --all --dir src\           render all in custom folder
REM   diagram.cmd --watch                    watch .\diagrams\ and auto-render
REM   diagram.cmd --server                   start PlantUML local HTTP server
REM   diagram.cmd --server --stop            stop PlantUML server
REM   diagram.cmd --check                    verify all dependencies
REM   diagram.cmd --help                     show this help
REM =============================================================================

setlocal enabledelayedexpansion

REM ── Config ───────────────────────────────────────────────────────────────────
if not defined PLANTUML_JAR set PLANTUML_JAR=%USERPROFILE%\plantuml.jar
if not defined PLANTUML_PORT set PLANTUML_PORT=8080
if not defined DIAGRAMS_DIR set DIAGRAMS_DIR=diagrams
set PLANTUML_SERVER=http://localhost:%PLANTUML_PORT%
set PID_FILE=.plantuml_server.pid
set FORMAT=png
set WATCH_DIR=%DIAGRAMS_DIR%
set CMD=help
set STOP=false
set FILE=

REM ── Parse arguments ──────────────────────────────────────────────────────────
:parse_args
if "%~1"=="" goto dispatch
if /i "%~1"=="--svg"    set FORMAT=svg & shift & goto parse_args
if /i "%~1"=="--all"    set CMD=all & shift & goto parse_args
if /i "%~1"=="--watch"  set CMD=watch & shift & goto parse_args
if /i "%~1"=="--server" set CMD=server & shift & goto parse_args
if /i "%~1"=="--check"  set CMD=check & shift & goto parse_args
if /i "%~1"=="--help"   set CMD=help & shift & goto parse_args
if /i "%~1"=="-h"       set CMD=help & shift & goto parse_args
if /i "%~1"=="--stop"   set STOP=true & shift & goto parse_args
if /i "%~1"=="--dir"    set WATCH_DIR=%~2 & shift & shift & goto parse_args
REM If it's not a flag and CMD is still help, treat as a file
if not "%~1"=="" if "!CMD!"=="help" (
    set FILE=%~1
    set CMD=single
)
shift
goto parse_args

REM ── Dispatch ─────────────────────────────────────────────────────────────────
:dispatch
if "!CMD!"=="single"  goto do_single
if "!CMD!"=="all"     goto do_all
if "!CMD!"=="watch"   goto do_watch
if "!CMD!"=="server"  goto do_server
if "!CMD!"=="check"   goto do_check
goto show_help

REM ── Single file render ────────────────────────────────────────────────────────
:do_single
if not exist "!FILE!" (
    echo   [ERR] File not found: !FILE!
    exit /b 1
)
call :render_file "!FILE!" "!FORMAT!"
goto :eof

REM ── Render all ────────────────────────────────────────────────────────────────
:do_all
if not exist "!WATCH_DIR!" (
    echo   [ERR] Directory not found: !WATCH_DIR!
    exit /b 1
)
echo.
echo ^> Rendering all diagrams in !WATCH_DIR! ...
echo.
set ok_count=0
set fail_count=0

for /r "!WATCH_DIR!" %%F in (*.puml *.plantuml *.mmd *.mermaid) do (
    call :render_file "%%F" "!FORMAT!"
    if !errorlevel! equ 0 (
        set /a ok_count+=1
    ) else (
        set /a fail_count+=1
    )
)

echo.
echo ---------------------------------
echo   [OK] Done -- !ok_count! rendered, !fail_count! failed
goto :eof

REM ── Watch (polling loop, 2s interval) ────────────────────────────────────────
:do_watch
if not exist "!WATCH_DIR!" mkdir "!WATCH_DIR!"
echo.
echo ^> Watching: !WATCH_DIR!
echo    Format : !FORMAT!
echo    Ctrl+C : Stop watcher
echo.

:watch_loop
for /r "!WATCH_DIR!" %%F in (*.puml *.plantuml *.mmd *.mermaid) do (
    set src=%%F
    set ext=%%~xF
    set out=%%~dpnF.!FORMAT!

    REM Check if source is newer than output
    if not exist "!out!" (
        echo.
        echo ^> New file: %%~nxF
        call :render_file "%%F" "!FORMAT!"
    ) else (
        REM xcopy /d trick: copies only if src is newer; use to detect change
        >nul 2>&1 xcopy /d /y "%%F" "%TEMP%\diag_check\" && (
            echo.
            echo ^> Changed: %%~nxF
            call :render_file "%%F" "!FORMAT!"
        )
    )
)
timeout /t 2 /nobreak >nul
goto watch_loop

REM ── Server management ────────────────────────────────────────────────────────
:do_server
if "!STOP!"=="true" goto server_stop

REM Check if already running
curl -s --max-time 2 !PLANTUML_SERVER! >nul 2>&1
if !errorlevel! equ 0 (
    echo   [OK] PlantUML server already running at !PLANTUML_SERVER!
    goto :eof
)

if not exist "!PLANTUML_JAR!" (
    echo   [ERR] plantuml.jar not found: !PLANTUML_JAR!
    echo         Download: https://plantuml.com/download
    echo         Or set:   set PLANTUML_JAR=D:\tools\plantuml.jar
    exit /b 1
)

echo ^> Starting PlantUML server on port !PLANTUML_PORT! ...
start /b "" java -jar "!PLANTUML_JAR!" -picoweb:!PLANTUML_PORT! >nul 2>&1

REM Wait up to 8s
set /a tries=0
:server_wait
timeout /t 1 /nobreak >nul
curl -s --max-time 1 !PLANTUML_SERVER! >nul 2>&1
if !errorlevel! equ 0 (
    echo   [OK] Server ready at !PLANTUML_SERVER!
    echo        Stop with: diagram.cmd --server --stop
    goto :eof
)
set /a tries+=1
if !tries! lss 8 goto server_wait
echo   [ERR] Server did not start in time. Check Java installation.
exit /b 1

:server_stop
if exist "!PID_FILE!" (
    set /p pid=<"!PID_FILE!"
    taskkill /pid !pid! /f >nul 2>&1
    del "!PID_FILE!" >nul 2>&1
    echo   [OK] PlantUML server stopped
) else (
    echo   [WARN] No PID file found
)
goto :eof

REM ── Dependency check ─────────────────────────────────────────────────────────
:do_check
echo.
echo ^> Checking dependencies ...
echo.

where java >nul 2>&1
if !errorlevel! equ 0 (
    for /f "tokens=*" %%v in ('java -version 2^>^&1') do (
        echo   [OK] Java      : %%v
        goto java_done
    )
) else (
    echo   [ERR] Java not found -- install from https://adoptium.net
)
:java_done

if exist "!PLANTUML_JAR!" (
    echo   [OK] plantuml.jar: !PLANTUML_JAR!
) else (
    echo   [ERR] plantuml.jar not found at: !PLANTUML_JAR!
    echo         Download: https://plantuml.com/download
)

curl -s --max-time 2 !PLANTUML_SERVER! >nul 2>&1
if !errorlevel! equ 0 (
    echo   [OK] PU Server  : running at !PLANTUML_SERVER!
) else (
    echo   [WARN] PU Server  : not running (optional)
    echo          Start with: diagram.cmd --server
)

where mmdc >nul 2>&1
if !errorlevel! equ 0 (
    for /f %%v in ('mmdc --version 2^>nul') do echo   [OK] mmdc       : %%v
) else (
    echo   [ERR] mmdc not found
    echo         Install: npm install -g @mermaid-js/mermaid-cli
)

echo.
goto :eof

REM ── Render file subroutine ────────────────────────────────────────────────────
:render_file
set src=%~1
set fmt=%~2
set ext=%~x1
set out=%~dpn1.%fmt%

REM PlantUML
if /i "%ext%"==".puml"     goto render_puml
if /i "%ext%"==".plantuml" goto render_puml
REM Mermaid
if /i "%ext%"==".mmd"      goto render_mmd
if /i "%ext%"==".mermaid"  goto render_mmd
echo   [WARN] Skipping unsupported extension: %ext%
exit /b 0

:render_puml
REM Try server first
curl -s --max-time 2 !PLANTUML_SERVER! >nul 2>&1
if !errorlevel! equ 0 (
    for /f %%e in ('python3 -c "import sys,zlib;t=open(sys.argv[1]).read();C=\"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_\";d=zlib.compress(t.encode())[2:-4];r=[];[r.__iadd__([C[(b:=(d[i]<<16)+((d[i+1] if i+1<len(d) else 0)<<8)+(d[i+2] if i+2<len(d) else 0))>>18&63],C[b>>12&63],C[b>>6&63] if i+1<len(d) else \"=\",C[b&63] if i+2<len(d) else \"=\"]) for i in range(0,len(d),3)];print(\"\".join(r))" "%src%" 2^>nul') do (
        curl -s --max-time 10 -o "%out%" "!PLANTUML_SERVER!/plantuml/%fmt%/%%e" >nul 2>&1
        if !errorlevel! equ 0 (
            echo   [OK][server] %~nx1 -^> %~n1.%fmt%
            exit /b 0
        )
    )
)

REM Fallback: java -jar
if not exist "!PLANTUML_JAR!" (
    echo   [ERR] plantuml.jar not found. Run: diagram.cmd --check
    exit /b 1
)
set flag=-tpng
if /i "%fmt%"=="svg" set flag=-tsvg
java -jar "!PLANTUML_JAR!" %flag% "%src%" >nul 2>&1
if !errorlevel! equ 0 (
    echo   [OK][jar]    %~nx1 -^> %~n1.%fmt%
    exit /b 0
) else (
    echo   [ERR] PlantUML render failed: %src%
    exit /b 1
)

:render_mmd
where mmdc >nul 2>&1
if !errorlevel! neq 0 (
    echo   [ERR] mmdc not found. Run: npm install -g @mermaid-js/mermaid-cli
    exit /b 1
)
mmdc -i "%src%" -o "%out%" -b white --quiet >nul 2>&1
if !errorlevel! equ 0 (
    echo   [OK][mmdc]   %~nx1 -^> %~n1.%fmt%
    exit /b 0
) else (
    echo   [ERR] Mermaid render failed: %src%
    exit /b 1
)

REM ── Help ─────────────────────────────────────────────────────────────────────
:show_help
echo.
echo   diagram.cmd -- local diagram renderer (PlantUML + Mermaid)
echo.
echo   Usage:
echo     diagram.cmd ^<file.puml^>          render single PlantUML file
echo     diagram.cmd ^<file.mmd^>           render single Mermaid file
echo     diagram.cmd ^<file^> --svg         render as SVG
echo     diagram.cmd --all                 render all in .\diagrams\
echo     diagram.cmd --all --svg           render all as SVG
echo     diagram.cmd --all --dir src\      render all in custom folder
echo     diagram.cmd --watch               auto-render on file save (2s poll)
echo     diagram.cmd --server              start PlantUML HTTP server
echo     diagram.cmd --server --stop       stop PlantUML server
echo     diagram.cmd --check               verify all dependencies
echo.
echo   Environment variables:
echo     PLANTUML_JAR    path to plantuml.jar  (default: %%USERPROFILE%%\plantuml.jar)
echo     PLANTUML_PORT   server port            (default: 8080)
echo     DIAGRAMS_DIR    default diagram folder (default: .\diagrams)
echo.
goto :eof
