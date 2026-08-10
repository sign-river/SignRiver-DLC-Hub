@echo off
chcp 65001 >nul
title Cities Skylines II Directory Probe
cd /d "%~dp0"

set "PY="
where py >nul 2>nul
if %errorlevel%==0 set "PY=py -3"
if defined PY goto :run
where python >nul 2>nul
if %errorlevel%==0 set "PY=python"
if defined PY goto :run
echo [ERROR] Python was not found on this computer.
echo Please install Python from https://www.python.org/downloads/
echo Remember to tick "Add python.exe to PATH" during installation.
pause
exit /b 1

:run
%PY% "%~dp0cs2_directory_probe.py" %*
set "RC=%errorlevel%"
echo.
pause
exit /b %RC%