@echo off
REM JARVIS launcher for Windows — double-click or run from a terminal.
REM Uses the repo virtualenv when present, otherwise the system Python.
setlocal
set ROOT=%~dp0..
set PY=%ROOT%\.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

if "%1"=="" (
  "%PY%" -m jarvis chat
) else (
  "%PY%" -m jarvis %*
)
endlocal
