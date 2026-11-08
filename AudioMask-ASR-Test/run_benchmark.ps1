[CmdletBinding()]
param(
    [ValidateSet('check-env','check-data','create-env','check-deps','resolve','install','download','verify-weights','run','compare','report','self-test','audit')]
    [string]$Action = 'check-env',
    [ValidateSet('whisper','gigaam-v3','gigaam-multi')]
    [string]$Model = 'whisper',
    [ValidateSet('3.12','3.13')]
    [string]$PythonVersion = '3.13',
    [string]$PythonExe,
    [string]$DataPath,
    [string]$OutputPath,
    [ValidateRange(1,86400)][int]$TimeoutSeconds = 7200,
    [ValidateRange(256,8192)][int]$RamLimitMiB = 7168,
    [switch]$AllowInstall,
    [switch]$AllowDownload,
    [switch]$AllowNetwork
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:CUDA_VISIBLE_DEVICES = '-1'
$env:HF_HOME = Join-Path $Root '.cache\huggingface'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
$env:PIP_INDEX_URL = 'https://pypi.org/simple'
$env:PIP_EXTRA_INDEX_URL = ''
$env:PIP_CACHE_DIR = Join-Path $Root '.cache\pip'
$env:OMP_NUM_THREADS = '4'
$env:MKL_NUM_THREADS = '4'
$env:OPENBLAS_NUM_THREADS = '4'
$env:TOKENIZERS_PARALLELISM = 'false'

function Invoke-Python {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python command failed (exit $LASTEXITCODE)." }
}

function Get-BasePython {
    if ($PythonExe) {
        $candidate = (Get-Command $PythonExe -ErrorAction Stop).Source
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $candidate = & py "-$PythonVersion" -c 'import sys; print(sys.executable)'
        if ($LASTEXITCODE -ne 0) { throw "Python $PythonVersion not found. Install it manually side by side, or pass -PythonExe." }
        $candidate = [string]$candidate
    } else {
        $candidate = (Get-Command python -ErrorAction Stop).Source
    }
    return $candidate
}

try {
    if (-not $DataPath) {
        $desktop = [Environment]::GetFolderPath('Desktop')
        if (-not $desktop) { throw 'Desktop path unavailable; pass -DataPath explicitly.' }
        $DataPath = Join-Path $desktop 'data'
    }
    if (-not $OutputPath) { $OutputPath = Join-Path $Root 'results' }
    $VenvPath = Join-Path $Root ".venvs\$Model-$PythonVersion"
    $VenvPython = Join-Path $VenvPath 'Scripts\python.exe'
    $Benchmark = Join-Path $Root 'benchmark.py'
    $Manage = Join-Path $Root 'manage.py'
    if ($Action -in @('check-env','check-data','create-env','report','self-test','audit')) {
        $BasePython = Get-BasePython
        if ($Action -eq 'check-env') {
            Invoke-Python $BasePython @('-B', $Benchmark, 'check-env', '--version', $PythonVersion)
            if (Test-Path -LiteralPath $VenvPython) {
                Invoke-Python $VenvPython @('-B', $Benchmark, 'check-env', '--version', $PythonVersion, '--require-venv')
            }
        } elseif ($Action -eq 'check-data') {
            Invoke-Python $BasePython @('-B', $Benchmark, 'check-data', '--data', $DataPath, '--output', (Join-Path $OutputPath 'validation'))
        } elseif ($Action -eq 'create-env') {
            Invoke-Python $BasePython @('-B', $Benchmark, 'check-env', '--version', $PythonVersion)
            if (-not (Test-Path -LiteralPath $VenvPath)) {
                Invoke-Python $BasePython @('-m', 'venv', $VenvPath)
            }
            Invoke-Python $VenvPython @('-B', $Benchmark, 'check-env', '--version', $PythonVersion, '--require-venv')
        } elseif ($Action -eq 'report') {
            Invoke-Python $BasePython @('-B', $Benchmark, 'report', '--output', $OutputPath)
        } elseif ($Action -eq 'self-test') {
            Invoke-Python $BasePython @('-B', (Join-Path $Root 'test_local.py'))
        } else {
            if (-not $AllowNetwork) { throw 'Metadata audit requires -AllowNetwork (PyPI metadata only, no packages/weights).' }
            Invoke-Python $BasePython @('-B', (Join-Path $Root 'compatibility.py'))
        }
        exit 0
    }
    if (-not (Test-Path -LiteralPath $VenvPython)) { throw "Create environment first: -Action create-env -Model $Model -PythonVersion $PythonVersion" }
    Invoke-Python $VenvPython @('-B', $Benchmark, 'check-env', '--version', $PythonVersion, '--require-venv')
    if ($Action -eq 'install' -or $Action -eq 'resolve') {
        if ($Action -eq 'install' -and -not $AllowInstall) { throw 'Installation denied. Explicit -AllowInstall is required.' }
        if ($Action -eq 'resolve' -and -not $AllowNetwork) { throw 'Resolver needs -AllowNetwork; it can download package metadata/distributions but installs nothing.' }
        $Req = Join-Path $Root "requirements-$Model.txt"
        $Logs = Join-Path $Root "results\environment\$Model-$PythonVersion"
        New-Item -ItemType Directory -Path $Logs -Force | Out-Null
        $PipCache = Join-Path $Root '.cache\pip'
        $Common = @('-m','pip','--isolated','--cache-dir',$PipCache,'install','--index-url','https://pypi.org/simple','--only-binary=:all:','--no-binary=antlr4-python3-runtime')
        if ($Action -eq 'resolve') {
            Invoke-Python $VenvPython ($Common + @('--dry-run','--ignore-installed','--report',(Join-Path $Logs 'resolution.json'),'-r',$Req))
        } else {
            Invoke-Python $VenvPython @('-m','pip','--isolated','--cache-dir',$PipCache,'install','--index-url','https://pypi.org/simple','--only-binary=:all:','setuptools>=70','wheel')
            if ($Model -ne 'whisper') {
                $TorchVersion = '2.8.0'
                if ($Model -eq 'gigaam-multi') { $TorchVersion = '2.10.0' }
                Invoke-Python $VenvPython @('-m','pip','--isolated','--cache-dir',$PipCache,'install','--index-url','https://download.pytorch.org/whl/cpu','--only-binary=:all:',"torch==$TorchVersion", "torchaudio==$TorchVersion")
            }
            Invoke-Python $VenvPython ($Common + @('--report',(Join-Path $Logs 'installation.json'),'-r',$Req))
            Invoke-Python $VenvPython @('-m','pip','check')
            & $VenvPython -m pip freeze | Set-Content -LiteralPath (Join-Path $Logs 'installed.txt') -Encoding UTF8
            if ($LASTEXITCODE -ne 0) { throw 'pip freeze failed' }
            Invoke-Python $VenvPython @('-B',$Manage,'check-deps','--model',$Model)
        }
    } elseif ($Action -eq 'check-deps') {
        Invoke-Python $VenvPython @('-m','pip','check')
        Invoke-Python $VenvPython @('-B',$Manage,'check-deps','--model',$Model)
    } elseif ($Action -eq 'download') {
        if (-not $AllowDownload) { throw 'Download denied. Explicit -AllowDownload is required.' }
        Invoke-Python $VenvPython @('-B',$Manage,'download','--model',$Model,'--allow-download')
    } elseif ($Action -eq 'verify-weights') {
        Invoke-Python $VenvPython @('-B',$Manage,'verify-weights','--model',$Model)
    } else {
        $Selected = $Model
        if ($Action -eq 'compare') { $Selected = 'all' }
        Invoke-Python $VenvPython @('-B',$Benchmark,'run','--model',$Selected,'--version',$PythonVersion,
            '--data',$DataPath,'--output',$OutputPath,'--timeout',"$TimeoutSeconds",'--ram-mib',"$RamLimitMiB")
    }
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
