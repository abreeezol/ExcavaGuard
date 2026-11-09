$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

try {
    # The CMD entry maps the WSL UNC directory to a drive for Windows tools.
    if (-not (Get-Command node.exe -ErrorAction SilentlyContinue)) {
        if (Test-Path 'D:\soft_install\nodejs\node.exe') {
            $env:Path = 'D:\soft_install\nodejs;' + $env:Path
        }
    }
    if (-not (Get-Command node.exe -ErrorAction SilentlyContinue)) {
        throw 'Windows Node.js is missing. Install Node.js 24 LTS and retry.'
    }
    $nodeVersion = [version](& node.exe -p 'process.versions.node')
    if (-not (($nodeVersion.Major -eq 22 -and $nodeVersion.Minor -ge 13) -or $nodeVersion.Major -eq 24 -or $nodeVersion.Major -ge 26)) {
        throw 'Use a supported Node.js version: 22.13+, 24, or 26+.'
    }
    Write-Host "Node.js $nodeVersion"

    $pythonPath = $null
    foreach ($candidate in @('py.exe', 'python.exe', 'python3.exe')) {
        if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
        $candidateArgs = @('-c', 'import sys; print(sys.executable)')
        if ($candidate -eq 'py.exe') { $candidateArgs = @('-3') + $candidateArgs }
        $output = @(& $candidate @candidateArgs 2>$null)
        if ($LASTEXITCODE -eq 0 -and $output -and (Test-Path ([string]$output[-1]))) {
            $pythonPath = [string]$output[-1]
            break
        }
    }
    if (-not $pythonPath) { throw 'Windows Python 3 is missing. Install Python 3 and retry.' }

    $testPython = Join-Path $PSScriptRoot '.tools\windows-python\Scripts\python.exe'
    if (-not (Test-Path $testPython)) {
        & $pythonPath -m venv (Join-Path $PSScriptRoot '.tools\windows-python')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the test Python environment.' }
    }
    & $testPython -c 'import importlib.util, sys; sys.exit(0 if all(importlib.util.find_spec(m) for m in [''openpyxl'', ''jsonschema'']) else 1)'
    if ($LASTEXITCODE -ne 0) {
        & $testPython -m pip install openpyxl 'jsonschema>=4.23'
        if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed. Check network access.' }
    }
    $env:EXCAVAGUARD_PYTHON = $testPython
    $env:PYTHONIOENCODING = 'utf-8'
    # Windows native directory watching does not work reliably on WSL shares.
    $env:WATCHPACK_POLLING = '1000'

    if (-not (Test-Path 'node_modules\next\package.json')) {
        Write-Host 'Installing project dependencies with npm ci...'
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed. Check the installation output above.' }
    }

    $port = $null
    foreach ($candidatePort in 3000..3010) {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $candidatePort)
        try {
            $listener.Start()
            $port = $candidatePort
            break
        } catch {
            # Try the next port without stopping existing applications.
        } finally { $listener.Stop() }
    }
    if (-not $port) { throw 'No available test port in 3000-3010.' }
    $url = "http://localhost:$port/workbench"
    Write-Host "Starting $url"
    Write-Host 'Using Webpack with 1-second polling for WSL network-path compatibility.'
    Write-Host 'Keep this window open. Press Ctrl+C to stop the test server.'
    $browserJob = Start-Job -ArgumentList $url -ScriptBlock {
        param($url)
        for ($i = 0; $i -lt 60; $i++) {
            try {
                $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
                if ($response.StatusCode -eq 200) {
                    Start-Process $url
                    return
                }
            } catch { }
            Start-Sleep -Seconds 2
        }
    }
    try {
        & npm.cmd run dev -- --webpack --port $port
        if ($LASTEXITCODE -ne 0) { throw 'The test server stopped with an error.' }
    } finally {
        Stop-Job $browserJob -ErrorAction SilentlyContinue
        Remove-Job $browserJob -Force -ErrorAction SilentlyContinue
    }
} catch {
    Write-Host ("STARTUP FAILED: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
