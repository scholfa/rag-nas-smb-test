<#
PowerShell smoke test for the RAG project
Checks Docker, Docker Compose, service endpoints, and attempts to list /docs inside the backend container
#>
Write-Output "=== RAG Project Smoke Test ==="

try {
    docker info > $null 2>&1
    Write-Output "✅ Docker is running"
} catch {
    Write-Error "❌ Docker not running or not accessible"
    exit 1
}

# Choose compose command
$composeCmd = if (Get-Command 'docker' -ErrorAction SilentlyContinue) {
    try {
        docker compose version > $null 2>&1; 'docker compose'
    } catch { 'docker-compose' }
} else { 'docker-compose' }

Write-Output "Using compose: $composeCmd"

Write-Output "--- Services ---"
& $composeCmd ps

Write-Output "--- Checking HTTP endpoints ---"
function Check-Http($url, $name) {
    try {
        $resp = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 5 -ErrorAction Stop
        Write-Output "✅ $name is responding: $url"
    } catch {
        Write-Output "❌ $name not responding: $url"
    }
}

Check-Http -url 'http://localhost:8000/health' -name 'Backend'
Check-Http -url 'http://localhost:3000' -name 'Frontend'
Check-Http -url 'http://localhost:11434/api/tags' -name 'Ollama'

Write-Output "--- Inspecting backend container for /docs (if running) ---"
$backend = docker ps --filter "name=rag-backend" --format "{{.Names}}"
if ($backend) {
    Write-Output "Found backend container: $backend"
    docker exec $backend powershell -Command "if (Test-Path -Path '/docs') { Get-ChildItem -Path '/docs' } else { Write-Output '/docs not present' }"
} else {
    Write-Output "Backend container not running, skipping /docs inspection"
}

Write-Output "=== Smoke Test Complete ==="
