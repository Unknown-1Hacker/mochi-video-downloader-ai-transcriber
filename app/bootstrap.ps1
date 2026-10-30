$ErrorActionPreference = 'Stop'
try {
    $Here = Split-Path -Parent $MyInvocation.MyCommand.Path
    if ((Split-Path -Leaf (Split-Path -Parent $Here)) -eq '.mochi') {
        $Root = Split-Path -Parent (Split-Path -Parent $Here)
    } else { $Root = Split-Path -Parent $Here }
    $State = Join-Path $Root '.mochi'
    $Tools = Join-Path $State 'tools'
    $Uv = Join-Path $Tools 'uv.exe'
    $Py = Join-Path $State 'venv\Scripts\python.exe'
    New-Item -ItemType Directory -Path $Tools -Force | Out-Null
    $env:UV_INSTALL_DIR = $Tools
    $env:UV_NO_MODIFY_PATH = '1'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $State 'python'
    $env:UV_CACHE_DIR = Join-Path $State 'cache'
    Write-Host '✦ Mochi is taking care of setup ✦' -ForegroundColor Magenta
    if (-not (Test-Path $Uv)) {
        $existing = Get-Command uv.exe -ErrorAction SilentlyContinue
        if ($existing) { $Uv = $existing.Source }
        else {
            $installer = Join-Path $State 'uv-install.ps1'
            Invoke-WebRequest -Uri 'https://astral.sh/uv/install.ps1' -OutFile $installer
            & $installer
            Remove-Item $installer -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not (Test-Path $Uv)) { throw 'Could not prepare setup helper.' }
    Write-Host '[1/4] Preparing private Python and video tools...'
    & $Uv venv --python 3.12 (Join-Path $State 'venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python setup failed.' }
    $Req = Join-Path $Here 'requirements.lock'
    if (-not (Test-Path $Req)) { $Req = Join-Path $Here 'requirements.txt' }
    & $Uv pip install --python $Py -r $Req
    if ($LASTEXITCODE -ne 0) { throw 'Python packages could not install.' }
    Write-Host '[2/4] Preparing audio and video tools...'
    & $Py (Join-Path $Here 'setup_ffmpeg.py')
    if ($LASTEXITCODE -ne 0) { throw 'Media setup failed.' }
    $DenoExe = Join-Path $State 'deno\bin\deno.exe'
    if (-not (Test-Path $DenoExe) -and -not (Get-Command deno.exe -ErrorAction SilentlyContinue)) {
        $denoInstaller = Join-Path $State 'deno-install.ps1'
        Invoke-WebRequest -Uri 'https://deno.land/install.ps1' -OutFile $denoInstaller
        $env:DENO_INSTALL = Join-Path $State 'deno'
        & $denoInstaller
        if (-not (Test-Path $DenoExe)) { throw 'Deno setup could not finish.' }
        Remove-Item $denoInstaller -Force -ErrorAction SilentlyContinue
    }
    Write-Host '[3/4] Organizing Mochi...'
    if (Test-Path (Join-Path $Root 'app')) {
        & $Py (Join-Path $Here 'install_layout.py') prepare
        if ($LASTEXITCODE -ne 0) { throw 'Organizing setup failed.' }
    }
    $env:PATH = (Join-Path $State 'deno\bin') + ';' + $env:PATH
    Write-Host '[4/4] Opening your studio...'
    & $Py (Join-Path $State 'app\launcher.py')
    if ($LASTEXITCODE -ne 0) { throw 'Mochi could not start.' }
    & $Py (Join-Path $State 'app\install_layout.py') finish
    if ($LASTEXITCODE -ne 0) { throw 'Could not finish cleanup.' }
    Write-Host '✨ All done! Next time, double-click Run Mochi Now.' -ForegroundColor Green
} catch {
    Write-Host ('SETUP ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'Your files and install helpers are kept for retry.'
    exit 1
}
