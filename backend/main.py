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

app = FastAPI(title="RAG Backend API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
DOCS_DIR = Path("/docs")
DATA_DIR = Path("/data")
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
    """Query Ollama LLM with context."""
    full_prompt = f"""Based on the following context, answer the question.

Context:
{context}

Question: {prompt}

Answer:"""
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{OLLAMA_HOST}/api/generate",
            json={
                "model": "llama3.1:8b",
                "prompt": full_prompt,
                "stream": False
            }
        )
        response.raise_for_status()
        return response.json()["response"]


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
            content = await file.read()
            text = extract_text_from_file(file.filename, content)
            chunks = chunk_text(text)
            
            # Generate embeddings
            embeddings = embedding_model.encode(chunks).tolist()
            
            # Add to collection
            ids = [f"{file.filename}_{i}" for i in range(len(chunks))]
            metadatas = [{"source": file.filename, "chunk": i} for i in range(len(chunks))]
            
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
        except Exception as e:
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
        raise HTTPException(status_code=400, detail="NAS directory not mounted")
    
    def process_nas_documents():
        processed = []
        errors = []
        
        supported_extensions = [".pdf", ".docx", ".xlsx", ".csv", ".md", ".txt", ".drawio"]
        
        for file_path in DOCS_DIR.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
                try:
                    with open(file_path, "rb") as f:
                        content = f.read()
                    
                    text = extract_text_from_file(file_path.name, content)
                    chunks = chunk_text(text)
                    
                    # Generate embeddings
                    embeddings = embedding_model.encode(chunks).tolist()
                    
                    # Add to collection
                    ids = [f"{file_path.name}_{i}" for i in range(len(chunks))]
                    metadatas = [{"source": str(file_path.relative_to(DOCS_DIR)), "chunk": i} for i in range(len(chunks))]
                    
                    collection.add(
                        embeddings=embeddings,
                        documents=chunks,
                        metadatas=metadatas,
                        ids=ids
                    )
                    
                    processed.append(file_path.name)
                except Exception as e:
                    errors.append({"file": str(file_path), "error": str(e)})
        
        return {"processed": len(processed), "errors": len(errors)}
    
    background_tasks.add_task(process_nas_documents)
    return {"status": "started", "message": "NAS document ingestion started in background"}


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    """Query the RAG system."""
    # Generate query embedding
    query_embedding = embedding_model.encode([request.query]).tolist()[0]
    
    # Search in vector store
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=request.top_k
    )
    
    if not results["documents"][0]:
        raise HTTPException(status_code=404, detail="No relevant documents found")
    
    # Prepare context from retrieved documents
    context = "\n\n".join(results["documents"][0])
    
    # Query Ollama with context
    try:
        answer = await query_ollama(request.query, context)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error querying Ollama: {str(e)}")
    
    # Prepare sources
    sources = []
    for i, (doc, metadata) in enumerate(zip(results["documents"][0], results["metadatas"][0])):
        sources.append({
            "source": metadata.get("source", "unknown"),
            "chunk": metadata.get("chunk", 0),
            "preview": doc[:200] + "..." if len(doc) > 200 else doc
        })
    
    return QueryResponse(answer=answer, sources=sources)


@app.delete("/clear")
async def clear_collection():
    """Clear all documents from the vector store."""
    global collection
    chroma_client.delete_collection(COLLECTION_NAME)
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )
    return {"status": "success", "message": "Collection cleared"}


@app.get("/stats")
async def get_stats():
    """Get statistics about the indexed documents."""
    count = collection.count()
    return {
        "total_chunks": count,
        "collection_name": COLLECTION_NAME
    }
