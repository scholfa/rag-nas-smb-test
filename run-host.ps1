param(
    [switch]$Detach
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if ($Detach) {
    docker compose -f docker-compose.host.yml up --build -d
} else {
    docker compose -f docker-compose.host.yml up --build
}
