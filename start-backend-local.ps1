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
    $unc = "\\$($env:NAS_HOST)\$($env:NAS_SHARE)"
    Write-Host "Detected NAS config. Constructed UNC path: $unc"
    if ($env:SMB_USER -and $env:SMB_PASS) {
        # Try mapping to drive Z: for convenience if it's free
        $drive = 'Z:'
        if (-not (Test-Path $drive)) {
            try {
                Write-Host "Mapping $unc to drive $drive"
                net use $drive $unc /user:$env:SMB_USER $env:SMB_PASS /persistent:no | Out-Null
                Write-Host "Mapped $unc to $drive"
                $env:DOCS_DIR = $drive
            } catch {
                Write-Host "Failed to map drive $drive to $unc - falling back to UNC path: $_"
                $env:DOCS_DIR = $unc
            }
        } else {
            Write-Host "$drive already in use - using UNC path $unc"
            $env:DOCS_DIR = $unc
        }
    } else {
        # No credentials provided - use UNC path (requires appropriate permissions)
        Write-Host "Using UNC path for DOCS_DIR: $unc (no SMB credentials provided)"
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
