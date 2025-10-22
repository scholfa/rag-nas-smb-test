Alternative: host-backend compose override

Standalone host-compose

If you prefer a single, standalone compose file that runs only the services that should remain in Docker while the backend runs on your host, use `docker-compose.host.yml`.

Start it with the helper scripts:

Linux/macOS:

```bash
./run-host.sh
```

Windows (PowerShell):

```powershell
.\run-host.ps1
# or detached
.\run-host.ps1 -Detach
```

`docker-compose.host.yml` launches the frontend (configured to call your host backend via `host.docker.internal`) and Ollama only.
# RAG System with NAS SMB Support

A complete Retrieval-Augmented Generation (RAG) system with document ingestion from NAS via SMB, powered by FastAPI, Chroma vector database, Sentence Transformers, and Llama 3.1.

## 🏗️ Architecture

The system consists of three Docker containers:

1. **Backend** (Port 8000): FastAPI service with:
   - Chroma vector database for embeddings
   - Sentence Transformers for text embeddings
   - Document parsers for multiple formats
   - RAG query processing with Ollama integration

2. **Frontend** (Port 3000): Gradio UI for:
   - Document upload and management
   - Natural language queries
   - System monitoring and statistics

3. **Ollama** (Port 11434): LLM service running:
   - Llama 3.1:8b model for response generation

## 📁 Supported File Formats

- ✅ PDF (`.pdf`)
- ✅ Word Documents (`.docx`)
- ✅ Excel Spreadsheets (`.xlsx`)
- ✅ CSV Files (`.csv`)
- ✅ Markdown (`.md`)
- ✅ Text Files (`.txt`)
- ✅ Draw.io Diagrams (`.drawio`) - Optional XML parsing

## 🚀 Quick Start

### Prerequisites

- Docker and Docker Compose installed
- Access to a NAS with SMB/CIFS share
- At least 8GB of RAM (for Llama 3.1:8b model)

Platform notes and OS-specific dependencies

- Linux / WSL2 / macOS
   - Docker Engine + Docker Compose (either `docker compose` or `docker-compose` should work)
   - CIFS utilities (on Linux) if you plan to mount SMB shares on the host
   - Use `./run.sh` and `./health-check.sh` to start and verify services

- Windows (Docker Desktop)
   - Docker Desktop (WSL2 backend recommended) — provides Docker Engine and Compose
   - Recommended: mount the SMB share on the Windows host (map network drive or `net use`) and bind-mount that host path into the container. Docker's CIFS local driver options in `docker-compose.yml` are not reliable on Windows.
   - Use `.run.ps1` and `.run.ps1 -Detach` to start services, and `.
      health-check.ps1` to verify
   - Run PowerShell as Administrator when creating mounts or when Docker Desktop requires elevated permissions for bind mounts

### Setup

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd rag-nas-smb-test
   ```

2. **Configure environment variables:**
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` with your NAS credentials:
   ```bash
   NAS_HOST=192.168.1.100          # Your NAS IP or hostname
   NAS_SHARE=documents             # Your SMB share name
   SMB_USER=your-username          # SMB username
   SMB_PASS=your-password          # SMB password
   ```

3. **Create the vectorstore directory:**
   ```bash
   mkdir -p vectorstore
   ```

4. **Start the services:**

Linux/macOS:

```bash
./run.sh
```

Windows (PowerShell):

```powershell
.\run.ps1
# or start detached
.\run.ps1 -Detach
```

   This will:
   - Build the backend and frontend containers
   - Pull and start the Ollama container
   - Download the Llama 3.1:8b model (this may take several minutes)
   - Mount your NAS share at `/docs` (read-only)
   - Create a persistent volume for the vector database

5. **Access the services:**
   - **Frontend UI**: http://localhost:3000
   - **Backend API**: http://localhost:8000
   - **API Documentation**: http://localhost:8000/docs
   - **Ollama API**: http://localhost:11434

## 📖 Usage

### Via Web UI (Gradio)

1. Open http://localhost:3000 in your browser

2. **Upload Documents** tab:
   - Upload individual files using the file selector
   - Or click "Ingest NAS Documents" to process all files from your NAS

3. **Query** tab:
   - Enter your question in natural language
   - Adjust the number of sources to retrieve (1-10)
   - Click "Ask" to get an AI-generated answer with sources

4. **System Info** tab:
   - Check backend health status
   - View indexing statistics
   - Clear all documents if needed

### Via API

#### Upload Documents
```bash
curl -X POST "http://localhost:8000/ingest/upload" \
  -F "files=@document.pdf" \
  -F "files=@spreadsheet.xlsx"
```

#### Ingest from NAS
```bash
curl -X POST "http://localhost:8000/ingest/nas"
```

#### Query Documents
```bash
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the key findings?",
    "top_k": 5
  }'
```

#### Get Statistics
```bash
curl http://localhost:8000/stats
```

#### Clear Collection
```bash
curl -X DELETE http://localhost:8000/clear
```

## 🔧 Configuration

### Docker Compose Volumes
### Docker Compose Volumes

- **docs_smb**: NAS documents mounted at `/docs` (read-only)
   - On Linux this uses a `local` volume with CIFS driver options (see `docker-compose.yml`).
   - On Windows Docker Desktop the CIFS volume driver options are often unsupported; recommended approaches:
      1. Mount the SMB share on the Windows host (map a network drive or `net use`) and bind-mount the host folder into the container using an override (see example below).
      2. Mount the SMB share inside WSL2 and bind-mount into the container if running under WSL2.

- **vectorstore**: Local persistent storage at `./vectorstore`
   - Stores Chroma vector database
   - Persists between container restarts

- **ollama_data**: Ollama model storage
   - Stores downloaded LLM models

Example bind-mount override (recommended for Windows hosts):

```yaml
services:
   backend:
      volumes:
         # Replace this path with your host-mounted NAS folder
         - C:/path/to/host/mounted/docs:/docs:ro
         - ./vectorstore:/data
      environment:
         - DEBUG=true
         - DOCS_DIR=/docs
         - DATA_DIR=/data
```

If you use a host bind mount, set `DOCS_DIR` and `DATA_DIR` in your `.env` or override to match the container paths.

### Environment Variables

Backend service:
- `OLLAMA_HOST`: Ollama service URL (default: `http://ollama:11434`)

Frontend service:
- `BACKEND_URL`: Backend API URL (default: `http://backend:8000`)

## 📊 System Requirements

- **CPU**: 4+ cores recommended
- **RAM**: 8GB minimum (16GB recommended)
- **Storage**: 
  - ~5GB for Llama 3.1:8b model
  - Variable for vector database (depends on document count)
- **Network**: Access to NAS via SMB

## 🐛 Troubleshooting

### NAS Mount Issues

If the NAS volume fails to mount:

1. Check NAS connectivity:
   ```bash
   ping <NAS_HOST>
   ```

2. Verify SMB credentials:
   ```bash
   smbclient -L //<NAS_HOST> -U <SMB_USER>
   ```

3. Check Docker logs:
   ```bash
   docker-compose logs backend
   ```

### Quick smoke tests

Two small smoke-test helpers are provided to quickly validate the runtime environment and service endpoints.

- Linux/macOS/WSL2:

```bash
./smoke-test.sh
```

- Windows (PowerShell):

```powershell
.\smoke-test.ps1
```

The scripts check Docker, show `docker compose ps`, probe the backend/frontend/Ollama HTTP endpoints, and attempt to list `/docs` inside the backend container if it's running.

### Ollama Model Not Loading

If Ollama fails to load the model:

1. Check Ollama logs:
   ```bash
   docker-compose logs ollama
   ```

2. Manually pull the model:
   ```bash
   docker-compose exec ollama ollama pull llama3.1:8b
   ```

### Backend Connection Issues

1. Verify all services are running:
   ```bash
   docker-compose ps
   ```

2. Check service health:
   ```bash
   curl http://localhost:8000/health
   curl http://localhost:11434/api/tags
   ```

## 🛠️ Development

### Running Services Individually

Backend:
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Frontend:
```bash
cd frontend
pip install -r requirements.txt
python app.py
```

### API Documentation

Interactive API documentation is available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 📝 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Health check |
| GET | `/health` | Detailed health status |
| POST | `/ingest/upload` | Upload and ingest documents |
| POST | `/ingest/nas` | Ingest documents from NAS |
| POST | `/query` | Query the RAG system |
| GET | `/stats` | Get indexing statistics |
| DELETE | `/clear` | Clear all documents |

## 🔐 Security Considerations

- SMB credentials are passed via environment variables
- The NAS volume is mounted as read-only for security
- **Important**: Never commit your `.env` file to version control. The `.gitignore` file excludes it by default.
- For production deployments, consider using Docker secrets or external secret management systems like HashiCorp Vault
- Ensure proper network isolation for the services
- Consider using encrypted SMB connections (SMB3 with encryption enabled on the NAS)

## 📦 Technology Stack

### Backend
- **FastAPI**: Modern Python web framework
- **Chroma**: Vector database for embeddings
- **Sentence Transformers**: Text embedding models
- **PyPDF**: PDF text extraction
- **python-docx**: Word document processing
- **pandas**: CSV/Excel data handling
- **openpyxl**: Excel file support
- **lxml**: XML parsing for Draw.io files

### Frontend
- **Gradio**: Interactive web UI framework

### LLM
- **Ollama**: Local LLM runtime
- **Llama 3.1:8b**: Language model for response generation

## 🤝 Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues.

## 📄 License

This project is provided as-is for educational and development purposes.