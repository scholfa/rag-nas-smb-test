import os
import io
from pathlib import Path
from typing import List, Optional, Dict
import uuid
import asyncio
import re
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
# Prefer GPU when available via PyTorch; SentenceTransformer accepts a device param.
try:
    import torch
    TORCH_AVAILABLE = True
except Exception:
    TORCH_AVAILABLE = False
import httpx
from pypdf import PdfReader
from docx import Document
import pandas as pd
import xml.etree.ElementTree as ET
import threading
import logging
import time

app = FastAPI(title="RAG Backend API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# configure logger
logger = logging.getLogger("rag_backend")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)
logger.setLevel(logging.INFO)

# Configuration
# Ollama / LLM configuration (tunable via environment)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_MAX_TOKENS = int(os.getenv("OLLAMA_MAX_TOKENS", "512"))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.0"))
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "120.0"))
# Allow overriding mount points for host-mounted folders (useful on Windows hosts)
# Default to repository-level `docs` and `vectorstore` so local runs behave sensibly.
repo_root = Path(__file__).resolve().parents[1]
# The environment variable DOCS_DIR may contain multiple paths separated by ';', ',' or '|'.
# We parse it into DOCS_DIRS (list[Path]) and use DOCS_DIRS throughout the code.
raw_docs = os.getenv("DOCS_DIR", str(repo_root / "docs"))
DOCS_DIRS = [Path(p.strip()) for p in re.split(r"[,;|]", raw_docs) if p.strip()]
DATA_DIR = Path(os.getenv("DATA_DIR", str(repo_root / "vectorstore")))
COLLECTION_NAME = "documents"

# Initialize embedding model
device = "cpu"
if TORCH_AVAILABLE:
    try:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        device = "cpu"

logger.info("Initializing SentenceTransformer on device=%s (torch_available=%s)", device, TORCH_AVAILABLE)
embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', device=device)

# Initialize Chroma client
chroma_client = chromadb.PersistentClient(
    path=str(DATA_DIR / "chroma"),
    settings=Settings(anonymized_telemetry=False)
)

# Get or create collection
collection = chroma_client.get_or_create_collection(
    name=COLLECTION_NAME,
    metadata={"hnsw:space": "cosine"}
)

# Thread lock for collection operations
collection_lock = threading.Lock()

# Task registries for cancellable operations
# ingest_tasks: task_id -> {thread, stop_event, status, result}
ingest_tasks: Dict[str, Dict] = {}
# query_tasks: request_id -> asyncio.Task
query_tasks: Dict[str, asyncio.Task] = {}

# Log configured paths so failures are easier to diagnose
for d in DOCS_DIRS:
    logger.info("Configured docs entry=%s exists=%s", d, d.exists())
logger.info("Configured DATA_DIR=%s exists=%s", DATA_DIR, DATA_DIR.exists())
logger.info("Configured OLLAMA_HOST=%s model=%s timeout=%.1fs max_tokens=%d", OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_MAX_TOKENS)


class QueryRequest(BaseModel):
    query: str
    top_k: int = 5
    # Optional per-request overrides for generation
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    # Optional client-provided id so frontend can abort
    request_id: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    sources: List[dict]


def extract_text_from_pdf(file_content: bytes) -> str:
    """Extract text from PDF file."""
    pdf_reader = PdfReader(io.BytesIO(file_content))
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text() + "\n"
    return text


def extract_text_from_docx(file_content: bytes) -> str:
    """Extract text from DOCX file."""
    doc = Document(io.BytesIO(file_content))
    text = ""
    for paragraph in doc.paragraphs:
        text += paragraph.text + "\n"
    return text


def extract_text_from_xlsx(file_content: bytes) -> str:
    """Extract text from XLSX file."""
    df = pd.read_excel(io.BytesIO(file_content), sheet_name=None)
    text = ""
    for sheet_name, sheet_df in df.items():
        text += f"Sheet: {sheet_name}\n"
        text += sheet_df.to_string(index=False) + "\n\n"
    return text


def extract_text_from_csv(file_content: bytes) -> str:
    """Extract text from CSV file."""
    df = pd.read_csv(io.BytesIO(file_content))
    return df.to_string(index=False)


def extract_text_from_drawio(file_content: bytes) -> str:
    """Extract text from Draw.io XML file."""
    try:
        root = ET.fromstring(file_content.decode('utf-8'))
        text_elements = []
        # Extract text from all elements with 'value' attribute
        for elem in root.iter():
            if 'value' in elem.attrib:
                text_elements.append(elem.attrib['value'])
        return "\n".join(text_elements)
    except Exception as e:
        return f"Error parsing drawio file: {str(e)}"


def extract_text_from_file(filename: str, content: bytes) -> str:
    """Extract text from various file types."""
    ext = Path(filename).suffix.lower()
    
    if ext == ".pdf":
        return extract_text_from_pdf(content)
    elif ext == ".docx":
        return extract_text_from_docx(content)
    elif ext == ".xlsx":
        return extract_text_from_xlsx(content)
    elif ext == ".csv":
        return extract_text_from_csv(content)
    elif ext in [".txt", ".md"]:
        return content.decode('utf-8', errors='ignore')
    elif ext == ".drawio":
        return extract_text_from_drawio(content)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """Split text into overlapping chunks."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk:
            chunks.append(chunk)
    return chunks


async def query_ollama(prompt: str, context: str, temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> str:
    """Query Ollama LLM with context. Model, timeout, and generation options are configurable via env vars.

    Returns the text result as a string. Raises httpx exceptions on transport errors.
    """
    full_prompt = f"""Based on the following context, answer the question.

Context:
{context}

Question: {prompt}

Answer:"""

    # Allow per-request overrides; fallback to configured defaults
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": full_prompt,
        "stream": False,
        # include generation options when supported by Ollama
        "max_tokens": int(max_tokens) if max_tokens is not None else OLLAMA_MAX_TOKENS,
        "temperature": float(temperature) if temperature is not None else OLLAMA_TEMPERATURE,
    }

    start = time.monotonic()
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        response = await client.post(f"{OLLAMA_HOST}/api/generate", json=payload)
        response.raise_for_status()
        elapsed = time.monotonic() - start
        logger.info("Ollama generate finished model=%s elapsed=%.2fs status=%d", OLLAMA_MODEL, elapsed, response.status_code)
        data = response.json()

        # Robust parsing of Ollama responses
        if isinstance(data, dict):
            # Common shapes: {"response": "..."} or {"result": "..."} or {"choices": [{"text": "..."}]}
            if "response" in data:
                return data["response"]
            if "result" in data:
                return data["result"]
            if "choices" in data and isinstance(data["choices"], list) and data["choices"]:
                first = data["choices"][0]
                if isinstance(first, dict):
                    return first.get("text") or first.get("message") or str(first)

        # Fallback: return stringified JSON
        return str(data)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "RAG Backend"}


@app.get("/health")
async def health():
    """Detailed health check."""
    collection_count = collection.count()
    return {
        "status": "healthy",
        "documents_indexed": collection_count,
        "ollama_host": OLLAMA_HOST
    }





@app.post("/ingest/nas")
async def ingest_nas():
    """Start a cancellable ingestion of documents from configured NAS mount points.
    Returns a task_id which can be used to abort or query status.
    """
    # Find which configured docs roots actually exist
    existing_dirs = [d for d in DOCS_DIRS if d.exists()]
    if not existing_dirs:
        raise HTTPException(status_code=400, detail=f"None of the configured NAS directories are mounted: {DOCS_DIRS}")

    task_id = str(uuid.uuid4())
    stop_event = threading.Event()

    def process_nas_documents(stop_event: threading.Event, task_id: str = task_id):
        processed = []
        errors = []

        supported_extensions = [".pdf", ".docx", ".xlsx", ".csv", ".md", ".txt", ".drawio"]

        for docs_root in existing_dirs:
            if stop_event.is_set():
                logger.info("Ingest task %s aborted before processing %s", task_id, docs_root)
                break

            for file_path in docs_root.rglob("*"):
                if stop_event.is_set():
                    logger.info("Ingest task %s abort requested, stopping", task_id)
                    break

                if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
                    try:
                        logger.info("Start processing NAS file: %s (task=%s)", file_path, task_id)
                        with open(file_path, "rb") as f:
                            content = f.read()

                        text = extract_text_from_file(file_path.name, content)
                        if stop_event.is_set():
                            logger.info("Ingest task %s stopping during chunking", task_id)
                            break

                        chunks = chunk_text(text)

                        # Generate embeddings
                        embeddings = embedding_model.encode(chunks).tolist()

                        # Add to collection with unique IDs using path relative to the docs_root
                        timestamp = int(time.time() * 1000000)  # microseconds for uniqueness
                        relative_path = str(file_path.relative_to(docs_root))
                        ids = [f"{relative_path}_{timestamp}_{i}" for i in range(len(chunks))]
                        metadatas = [{"source": relative_path, "path": str(file_path), "chunk": i} for i in range(len(chunks))]

                        with collection_lock:
                            collection.add(
                                embeddings=embeddings,
                                documents=chunks,
                                metadatas=metadatas,
                                ids=ids
                            )

                        processed.append(file_path.name)
                        logger.info("Finished processing NAS file: %s (chunks=%d) (task=%s)", file_path, len(chunks), task_id)
                    except Exception as e:
                        logger.exception("Error processing NAS file: %s (task=%s)", file_path, task_id)
                        errors.append({"file": str(file_path), "error": str(e)})

        ingest_tasks.get(task_id, {}).update({"status": "stopped"})
        logger.info("NAS ingestion completed for task=%s. processed=%d errors=%d", task_id, len(processed), len(errors))
        ingest_tasks.get(task_id, {}).update({"result": {"processed": len(processed), "errors": len(errors)}})

    thread = threading.Thread(target=process_nas_documents, args=(stop_event,), daemon=True)
    ingest_tasks[task_id] = {"thread": thread, "stop_event": stop_event, "status": "running"}
    thread.start()

    logger.info("NAS document ingestion started in background (task_id=%s)", task_id)
    return {"status": "started", "task_id": task_id}


@app.post("/ingest/nas/abort")
async def abort_ingest(task_id: str):
    """Abort a running ingest task by task_id."""
    info = ingest_tasks.get(task_id)
    if not info:
        raise HTTPException(status_code=404, detail="Ingest task not found")
    if info.get("status") != "running":
        return {"status": "not-running", "task_id": task_id}

    info["stop_event"].set()
    thread = info.get("thread")
    thread.join(timeout=5)
    info["status"] = "aborted"
    logger.info("Ingest task %s aborted", task_id)
    return {"status": "aborted", "task_id": task_id}


@app.get("/ingest/nas/status")
async def ingest_status(task_id: str):
    info = ingest_tasks.get(task_id)
    if not info:
        raise HTTPException(status_code=404, detail="Ingest task not found")
    return {"task_id": task_id, "status": info.get("status"), "result": info.get("result")}


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    """Query the RAG system. Supports client-provided request_id so queries can be aborted via /query/abort.
    If no request_id is provided one will be generated for internal tracking only.
    """
    # Assign or generate a request id for cancellation
    req_id = request.request_id or str(uuid.uuid4())

    try:
        # Generate query embedding
        query_embedding = embedding_model.encode([request.query]).tolist()[0]

        # Search in vector store
        with collection_lock:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=request.top_k
            )

        # Validate results structure safely
        documents = results.get("documents") if isinstance(results, dict) else None
        metadatas = results.get("metadatas") if isinstance(results, dict) else None

        if not documents or not isinstance(documents, list) or not documents[0]:
            logger.info("No relevant documents found for query: %s", request.query)
            raise HTTPException(status_code=404, detail="No relevant documents found")

        # Prepare context from retrieved documents
        context = "\n\n".join(documents[0])

        # Create an asyncio task to call the LLM so it can be cancelled by request_id
        llm_task = asyncio.create_task(
            query_ollama(request.query, context, temperature=request.temperature, max_tokens=request.max_tokens)
        )
        query_tasks[req_id] = llm_task

        try:
            answer = await llm_task
        except asyncio.CancelledError:
            logger.info("Query task %s cancelled by client", req_id)
            raise HTTPException(status_code=499, detail="Query aborted by client")
        except httpx.TimeoutException as te:
            logger.exception("Timeout when querying Ollama: %s", te)
            raise HTTPException(status_code=504, detail="Timeout while querying LLM (Ollama)")
        except httpx.RequestError as re:
            logger.exception("HTTP error when querying Ollama: %s", re)
            raise HTTPException(status_code=502, detail=f"Error communicating with LLM: {str(re)}")
        finally:
            # Clean up task registry
            query_tasks.pop(req_id, None)

        # Prepare sources
        sources = []
        # guard metadatas shape
        meta_list = metadatas[0] if metadatas and isinstance(metadatas, list) and metadatas[0] else [{}] * len(documents[0])
        for i, (doc, metadata) in enumerate(zip(documents[0], meta_list)):
            try:
                src = metadata.get("source", "unknown") if isinstance(metadata, dict) else "unknown"
                path = metadata.get("path", src) if isinstance(metadata, dict) else src
                chunk = metadata.get("chunk", 0) if isinstance(metadata, dict) else 0
            except Exception:
                src = "unknown"
                path = "unknown"
                chunk = 0

            sources.append({
                "source": src,
                "path": path,
                "chunk": chunk,
                "preview": doc[:200] + "..." if isinstance(doc, str) and len(doc) > 200 else (doc or "")
            })

        return QueryResponse(answer=answer, sources=sources)
    except HTTPException:
        # Re-raise HTTPException so FastAPI handles it unchanged
        raise
    except Exception as e:
        logger.exception("Unhandled error in /query for query=%s: %s", request.query, e)
        raise HTTPException(status_code=500, detail="Internal server error processing query")


@app.delete("/clear")
async def clear_collection():
    """Clear all documents from the vector store."""
    global collection
    with collection_lock:
        chroma_client.delete_collection(COLLECTION_NAME)
        collection = chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
    return {"status": "success", "message": "Collection cleared"}


@app.get("/stats")
async def get_stats():
    """Get statistics about the indexed documents."""
    with collection_lock:
        count = collection.count()
    return {
        "total_chunks": count,
        "collection_name": COLLECTION_NAME
    }


@app.post("/query/abort")
async def abort_query(request_id: str):
    """Abort a running query identified by request_id. Returns 404 if not found."""
    task = query_tasks.get(request_id)
    if not task:
        raise HTTPException(status_code=404, detail="Query task not found")

    task.cancel()
    # Give a small grace period for cancellation
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=3.0)
    except asyncio.TimeoutError:
        logger.info("Timed out waiting for query task %s to cancel", request_id)
    except Exception:
        # Task may raise CancelledError which is okay
        pass

    query_tasks.pop(request_id, None)
    logger.info("Query task %s cancelled", request_id)
    return {"status": "cancelled", "request_id": request_id}
