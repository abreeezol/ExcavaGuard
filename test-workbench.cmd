@echo off
setlocal
title ExcavaGuard - Workbench Test
pushd "%~dp0"
if errorlevel 1 (
  echo Cannot access the project directory.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\test-workbench.ps1"
set "TEST_EXIT=%ERRORLEVEL%"
popd
if not "%TEST_EXIT%"=="0" pause
exit /b %TEST_EXIT%
