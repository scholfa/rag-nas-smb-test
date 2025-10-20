#!/usr/bin/env bash
# Health check script for the RAG system

echo "=== RAG System Health Check ==="
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running"
    exit 1
fi
echo "✅ Docker is running"

# Check if services are up
echo ""
echo "=== Service Status ==="
docker compose ps

# Check backend health
echo ""
echo "=== Backend Health ==="
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✅ Backend is responding"
    curl -s http://localhost:8000/health | python3 -m json.tool
else
    echo "❌ Backend is not responding"
fi

# Check Ollama health
echo ""
echo "=== Ollama Health ==="
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✅ Ollama is responding"
    curl -s http://localhost:11434/api/tags | python3 -m json.tool
else
    echo "❌ Ollama is not responding"
fi

# Check frontend health
echo ""
echo "=== Frontend Health ==="
if curl -s http://localhost:3000 > /dev/null 2>&1; then
    echo "✅ Frontend is responding"
else
    echo "❌ Frontend is not responding"
fi

# Check volumes
echo ""
echo "=== Volume Status ==="
docker volume ls | grep -E "docs_smb|ollama_data|vectorstore"

echo ""
echo "=== Health Check Complete ==="
