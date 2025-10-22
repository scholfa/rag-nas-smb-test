<#
Start the project using Docker Compose (PowerShell)
#>
param(
    [switch]$Detach
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

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
