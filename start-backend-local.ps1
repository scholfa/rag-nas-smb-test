param(
    [switch]$Detach
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Push-Location backend

if (-not (Test-Path -Path .venv)) {
    python -m venv .venv
}

$venvPath = (Get-Item .venv).FullName
$venvPython = Join-Path -Path $venvPath -ChildPath "Scripts\python.exe"
$venvPip = Join-Path -Path $venvPath -ChildPath "Scripts\pip.exe"

Start-Process -FilePath $venvPip -ArgumentList 'install','--upgrade','pip' -NoNewWindow -Wait
Start-Process -FilePath $venvPip -ArgumentList 'install','-r','requirements.txt' -NoNewWindow -Wait

# Load .env from repo root if present
$envFile = Join-Path $root '.env'
if (Test-Path $envFile) {
    Write-Host "Loading environment from $envFile"
    Get-Content $envFile | ForEach-Object {
        if ($_ -and -not $_.StartsWith('#')) {
            $parts = $_ -split '=', 2
            if ($parts.Count -eq 2) {
                $name = $parts[0].Trim()
                $value = $parts[1].Trim().Trim('"')
                Set-Item -Path Env:\$name -Value $value
            }
        }
    }
}

# Set sensible defaults for local backend
# If NAS configuration is present in .env, prefer the NAS UNC path (or map a drive when credentials provided)
if ($env:NAS_HOST -and $env:NAS_SHARE) {
    # Support multiple shares separated by comma/semicolon/pipe
    $shares = $env:NAS_SHARE -split '[,;|]'
    $uncs = @()
    foreach ($s in $shares) {
        $t = $s.Trim()
        if ($t) { $uncs += "\\$($env:NAS_HOST)\$t" }
    }

    if ($uncs.Count -gt 1) {
        # Multiple shares configured — set DOCS_DIR to semicolon-separated list and skip mapping
        $joined = ($uncs -join ';')
        Write-Host "Detected multiple NAS shares. Setting DOCS_DIR to: $joined"
        $env:DOCS_DIR = $joined
    } else {
        # Single share configured — always use UNC path. Drive-letter mapping is disabled to avoid
        # interfering with existing user mappings and credentials issues.
        $unc = $uncs[0]
        Write-Host "Detected NAS config. Using UNC path for DOCS_DIR: $unc (drive-letter mapping disabled)"
        $env:DOCS_DIR = $unc
    }
} elseif ($env:DOCS_HOST_PATH) {
    $env:DOCS_DIR = $env:DOCS_HOST_PATH
} elseif (Test-Path (Join-Path $root 'docs')) {
    $env:DOCS_DIR = Join-Path $root 'docs'
} else {
    if (-not $env:DOCS_DIR) { $env:DOCS_DIR = Join-Path $root 'docs' }
}

if (-not $env:DATA_DIR) { $env:DATA_DIR = Join-Path $root 'vectorstore' }
if (-not $env:OLLAMA_HOST) { $env:OLLAMA_HOST = 'http://localhost:11434' }

Write-Host "Starting backend (local venv) with DOCS_DIR=$env:DOCS_DIR DATA_DIR=$env:DATA_DIR OLLAMA_HOST=$env:OLLAMA_HOST"

if ($Detach) {
    Start-Process -FilePath $venvPython -ArgumentList '-m','uvicorn','main:app','--host','0.0.0.0','--port','8000','--reload' -NoNewWindow -PassThru | Out-Null
} else {
    & $venvPython -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
}

Pop-Location
