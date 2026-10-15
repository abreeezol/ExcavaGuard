@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem ============================================================
rem  ExcavaGuard 本地 Demo 一键启动 (Windows)
rem  端口自动探测：占用或落在系统保留段时自动改用可用端口
rem ============================================================

set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [错误] 未找到虚拟环境： %PY%
    echo.
    echo 请先按 DEPLOY.md 第三章创建虚拟环境并安装依赖：
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install --upgrade pip
    echo     .venv\Scripts\python.exe -m pip install openpyxl fastapi uvicorn pydantic "chromadb>=1.0" torch "sentence-transformers>=3.0"
    echo.
    pause
    exit /b 1
)

"%PY%" "%~dp0start_demo.py" --open
pause
