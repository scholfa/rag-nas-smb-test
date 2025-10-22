import os
import io
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
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
DOCS_DIR = Path(os.getenv("DOCS_DIR", str(repo_root / "docs")))
DATA_DIR = Path(os.getenv("DATA_DIR", str(repo_root / "vectorstore")))
COLLECTION_NAME = "documents"

# Initialize embedding model
embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

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

# Log configured paths so failures are easier to diagnose
logger.info("Configured DOCS_DIR=%s exists=%s", DOCS_DIR, DOCS_DIR.exists())
logger.info("Configured DATA_DIR=%s exists=%s", DATA_DIR, DATA_DIR.exists())
logger.info("Configured OLLAMA_HOST=%s model=%s timeout=%.1fs max_tokens=%d", OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_MAX_TOKENS)


class QueryRequest(BaseModel):
    query: str
    top_k: int = 5


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


async def query_ollama(prompt: str, context: str) -> str:
    """Query Ollama LLM with context. Model, timeout, and generation options are configurable via env vars.

    Returns the text result as a string. Raises httpx exceptions on transport errors.
    """
    full_prompt = f"""Based on the following context, answer the question.

Context:
{context}

Question: {prompt}

Answer:"""

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": full_prompt,
        "stream": False,
        # include generation options when supported by Ollama
        "max_tokens": OLLAMA_MAX_TOKENS,
        "temperature": OLLAMA_TEMPERATURE,
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


@app.post("/ingest/upload")
async def ingest_upload(files: List[UploadFile] = File(...)):
    """Ingest uploaded documents into the vector store."""
    processed = []
    errors = []
    
    for file in files:
        try:
            logger.info("Start processing upload file: %s", file.filename)
            content = await file.read()
            text = extract_text_from_file(file.filename, content)
            chunks = chunk_text(text)
            
            # Generate embeddings
            embeddings = embedding_model.encode(chunks).tolist()
            
            # Add to collection with unique IDs using timestamp
            import time
            timestamp = int(time.time() * 1000000)  # microseconds for uniqueness
            ids = [f"{file.filename}_{timestamp}_{i}" for i in range(len(chunks))]
            metadatas = [{"source": file.filename, "chunk": i} for i in range(len(chunks))]
            
            with collection_lock:
                collection.add(
                    embeddings=embeddings,
                    documents=chunks,
                    metadatas=metadatas,
                    ids=ids
                )
            
            processed.append({
                "filename": file.filename,
                "chunks": len(chunks),
                "status": "success"
            })
            logger.info("Finished processing upload file: %s (chunks=%d)", file.filename, len(chunks))
        except Exception as e:
            logger.exception("Error processing upload file: %s", file.filename)
            errors.append({
                "filename": file.filename,
                "error": str(e)
            })
    
    return {
        "processed": processed,
        "errors": errors
    }


@app.post("/ingest/nas")
async def ingest_nas(background_tasks: BackgroundTasks):
    """Ingest all documents from NAS mount point."""
    if not DOCS_DIR.exists():
        # Include the expected path in the response so callers (frontend) can see
        # where the server is looking for the NAS mount.
        raise HTTPException(status_code=400, detail=f"NAS directory not mounted: {DOCS_DIR}")
    
    def process_nas_documents():
        processed = []
        errors = []
        
        supported_extensions = [".pdf", ".docx", ".xlsx", ".csv", ".md", ".txt", ".drawio"]
        
        for file_path in DOCS_DIR.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
                try:
                    logger.info("Start processing NAS file: %s", file_path)
                    with open(file_path, "rb") as f:
                        content = f.read()
                    
                    text = extract_text_from_file(file_path.name, content)
                    chunks = chunk_text(text)
                    
                    # Generate embeddings
                    embeddings = embedding_model.encode(chunks).tolist()
                    
                    # Add to collection with unique IDs using full path
                    import time
                    timestamp = int(time.time() * 1000000)  # microseconds for uniqueness
                    relative_path = str(file_path.relative_to(DOCS_DIR))
                    ids = [f"{relative_path}_{timestamp}_{i}" for i in range(len(chunks))]
                    metadatas = [{"source": str(file_path.relative_to(DOCS_DIR)), "chunk": i} for i in range(len(chunks))]
                    
                    with collection_lock:
                        collection.add(
                            embeddings=embeddings,
                            documents=chunks,
                            metadatas=metadatas,
                            ids=ids
                        )
                    
                    processed.append(file_path.name)
                    logger.info("Finished processing NAS file: %s (chunks=%d)", file_path, len(chunks))
                except Exception as e:
                    logger.exception("Error processing NAS file: %s", file_path)
                    errors.append({"file": str(file_path), "error": str(e)})
        
        logger.info("NAS ingestion completed. processed=%d errors=%d", len(processed), len(errors))
        return {"processed": len(processed), "errors": len(errors)}
    
    background_tasks.add_task(process_nas_documents)
    logger.info("NAS document ingestion started in background")
    return {"status": "started", "message": "NAS document ingestion started in background"}


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    """Query the RAG system."""
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

        # Query Ollama with context — handle network/timeouts separately
        try:
            answer = await query_ollama(request.query, context)
        except httpx.TimeoutException as te:
            logger.exception("Timeout when querying Ollama: %s", te)
            raise HTTPException(status_code=504, detail="Timeout while querying LLM (Ollama)")
        except httpx.RequestError as re:
            logger.exception("HTTP error when querying Ollama: %s", re)
            raise HTTPException(status_code=502, detail=f"Error communicating with LLM: {str(re)}")

        # Prepare sources
        sources = []
        # guard metadatas shape
        meta_list = metadatas[0] if metadatas and isinstance(metadatas, list) and metadatas[0] else [{}] * len(documents[0])
        for i, (doc, metadata) in enumerate(zip(documents[0], meta_list)):
            try:
                src = metadata.get("source", "unknown") if isinstance(metadata, dict) else "unknown"
                chunk = metadata.get("chunk", 0) if isinstance(metadata, dict) else 0
            except Exception:
                src = "unknown"
                chunk = 0

            sources.append({
                "source": src,
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
