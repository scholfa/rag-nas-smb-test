<#
.SYNOPSIS
  Health check script for the RAG system (PowerShell)

.DESCRIPTION
  Performs similar checks to `health-check.sh` for Windows/PowerShell environments:
  - Verifies Docker is running
  - Shows docker compose ps
  - Checks backend, Ollama and frontend HTTP endpoints
  - Lists relevant docker volumes
#>

Write-Output "=== RAG System Health Check ==="
Write-Output ""

# Check if Docker is running
try {
    docker info > $null 2>&1
    if ($LASTEXITCODE -ne 0) { throw }
    Write-Output "✅ Docker is running"
} catch {
    Write-Error "❌ Docker is not running or not available in PATH"
    exit 1
}

Write-Output ""
Write-Output "=== Service Status ==="
docker compose ps

Write-Output ""
Write-Output "=== Backend Health ==="
try {
    $backendResp = Invoke-RestMethod -Uri http://localhost:8000/health -Method Get -TimeoutSec 5 -ErrorAction Stop
    Write-Output "✅ Backend is responding"
    $backendResp | ConvertTo-Json -Depth 5 | Write-Output
} catch {
    Write-Output "❌ Backend is not responding"
}

Write-Output ""
Write-Output "=== Ollama Health ==="
try {
    $ollamaResp = Invoke-RestMethod -Uri http://localhost:11434/api/tags -Method Get -TimeoutSec 5 -ErrorAction Stop
    Write-Output "✅ Ollama is responding"
    $ollamaResp | ConvertTo-Json -Depth 5 | Write-Output
} catch {
    Write-Output "❌ Ollama is not responding"
}

Write-Output ""
Write-Output "=== Frontend Health ==="
try {
    Invoke-RestMethod -Uri http://localhost:3000 -Method Get -TimeoutSec 5 -ErrorAction Stop > $null
    Write-Output "✅ Frontend is responding"
} catch {
    Write-Output "❌ Frontend is not responding"
}

Write-Output ""
Write-Output "=== Volume Status ==="
try {
    $volumes = docker volume ls --format "{{.Name}}"
    $volumes -match "docs_smb|ollama_data|vectorstore" | ForEach-Object { Write-Output "- $_" }
} catch {
    Write-Output "Unable to list docker volumes"
}

Write-Output ""
Write-Output "=== Health Check Complete ==="
