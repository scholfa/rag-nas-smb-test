<#
Start the project using Docker Compose (PowerShell)
#>
param(
    [switch]$Detach
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# If example override exists and no override file present, copy it
if (Test-Path docker-compose.override.yml.example -PathType Leaf -and -not (Test-Path docker-compose.override.yml)) {
    Write-Output "Using example override file -> docker-compose.override.yml"
    Copy-Item -Path docker-compose.override.yml.example -Destination docker-compose.override.yml
}

if ($Detach) {
    Write-Output "Starting services in detached mode..."
    if (Get-Command 'docker' -ErrorAction SilentlyContinue) {
        try { docker compose up --build -d } catch { docker-compose up --build -d }
    } else {
        docker-compose up --build -d
    }
} else {
    Write-Output "Starting services... (press Ctrl+C to stop)"
    if (Get-Command 'docker' -ErrorAction SilentlyContinue) {
        try { docker compose up --build } catch { docker-compose up --build }
    } else {
        docker-compose up --build
    }
}
