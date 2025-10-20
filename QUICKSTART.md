# Quick Start Guide

## Prerequisites
- Docker & Docker Compose
- NAS with SMB share
- 8GB+ RAM

## Setup (5 minutes)

1. **Clone & Configure**
   ```bash
   git clone <repository-url>
   cd rag-nas-smb-test
   cp .env.example .env
   # Edit .env with your NAS details
   ```

2. **Start Services**
   ```bash
   mkdir vectorstore
   docker compose up -d
   ```

3. **Wait for Model Download** (~5-10 minutes first time)
   ```bash
   docker compose logs -f ollama
   # Wait until you see "llama3.1:8b"
   ```

4. **Access the UI**
   Open http://localhost:3000

## First Use

1. **Upload Documents**
   - Go to "Document Management" tab
   - Click "Select files" and choose your documents
   - Click "Upload and Process"

2. **Or Ingest from NAS**
   - Click "Ingest NAS Documents"
   - All documents from your NAS share will be processed

3. **Ask Questions**
   - Go to "Query" tab
   - Type your question
   - Get AI-powered answers with sources

## Troubleshooting

**NAS not mounting?**
```bash
# Test connectivity
ping <your-nas-ip>

# Check logs
docker compose logs backend

# Verify credentials in .env
```

**Ollama model not loading?**
```bash
# Check status
docker compose logs ollama

# Manually pull
docker compose exec ollama ollama pull llama3.1:8b
```

**Services not starting?**
```bash
# Check status
docker compose ps

# View logs
docker compose logs
```

## Commands

```bash
# Start services
docker compose up -d

# Stop services
docker compose down

# View logs
docker compose logs -f

# Restart a service
docker compose restart backend

# Clear all data
docker compose down -v
rm -rf vectorstore
```

## Environment Variables

Required in `.env`:
```bash
NAS_HOST=192.168.1.100    # Your NAS IP or hostname
NAS_SHARE=documents       # SMB share name
SMB_USER=username         # SMB username
SMB_PASS=password         # SMB password
```

## Supported File Formats
✅ PDF, DOCX, XLSX, CSV, MD, TXT, DRAWIO

## Ports
- 3000: Gradio UI
- 8000: Backend API
- 11434: Ollama

## Need Help?
- Check the full README.md
- View API docs: http://localhost:8000/docs
- Check system status in the "System Info" tab
