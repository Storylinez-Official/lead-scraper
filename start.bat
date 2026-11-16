@echo off
rem Double-click to set up (first time) and open the LeadScraper dashboard.
rem Extra arguments are passed through, e.g.  start.bat run --limit 5
cd /d "%~dp0"
set "PYCMD=python"
where py >nul 2>nul && set "PYCMD=py -3"
%PYCMD% start.py %*
if errorlevel 1 (
  echo.
  echo Something went wrong. If Python is missing, install Python 3.10+ from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during install.
  pause
)
