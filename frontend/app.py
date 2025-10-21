import os
import gradio as gr
import httpx
from typing import List

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")


async def check_backend_health():
    """Check if backend is healthy."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{BACKEND_URL}/health", timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                return f"✅ Backend is healthy. Documents indexed: {data.get('documents_indexed', 0)}"
            else:
                return "❌ Backend is not responding properly"
    except Exception as e:
        return f"❌ Backend connection error: {str(e)}"


async def upload_documents(files):
    """Upload documents to the backend for ingestion."""
    if not files:
        return "❌ No files selected"
    
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            # Process files one at a time to avoid memory issues
            all_processed = []
            all_errors = []
            
            for file in files:
                try:
                    with open(file.name, "rb") as f:
                        file_data = [("files", (os.path.basename(file.name), f.read()))]
                    
                    response = await client.post(
                        f"{BACKEND_URL}/ingest/upload",
                        files=file_data
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        all_processed.extend(data.get("processed", []))
                        all_errors.extend(data.get("errors", []))
                    else:
                        all_errors.append({
                            "filename": os.path.basename(file.name),
                            "error": f"Upload failed: {response.text}"
                        })
                except Exception as e:
                    all_errors.append({
                        "filename": os.path.basename(file.name),
                        "error": str(e)
                    })
            
            result = f"✅ Successfully processed {len(all_processed)} files\n\n"
            for item in all_processed:
                result += f"- {item['filename']}: {item['chunks']} chunks\n"
            
            if all_errors:
                result += f"\n❌ {len(all_errors)} errors:\n"
                for error in all_errors:
                    result += f"- {error['filename']}: {error['error']}\n"
            
            return result
    except Exception as e:
        return f"❌ Error uploading files: {str(e)}"


async def ingest_nas_documents():
    """Trigger NAS document ingestion."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(f"{BACKEND_URL}/ingest/nas")
            
            if response.status_code == 200:
                data = response.json()
                return f"✅ {data.get('message', 'NAS ingestion started')}"
            else:
                return f"❌ NAS ingestion failed: {response.text}"
    except Exception as e:
        return f"❌ Error triggering NAS ingestion: {str(e)}"


async def query_documents(query: str, top_k: int):
    """Query the RAG system."""
    if not query or query.strip() == "":
        return "❌ Please enter a question", ""
    
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            response = await client.post(
                f"{BACKEND_URL}/query",
                json={"query": query, "top_k": top_k}
            )
            
            if response.status_code == 200:
                data = response.json()
                answer = data.get("answer", "No answer generated")
                sources = data.get("sources", [])
                
                sources_text = "\n\n### Sources:\n"
                for i, source in enumerate(sources, 1):
                    sources_text += f"\n**{i}. {source['source']}** (chunk {source['chunk']})\n"
                    sources_text += f"```\n{source['preview']}\n```\n"
                
                return answer, sources_text
            else:
                error_detail = response.json().get("detail", response.text)
                return f"❌ Query failed: {error_detail}", ""
    except Exception as e:
        return f"❌ Error querying: {str(e)}", ""


async def get_stats():
    """Get statistics about indexed documents."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{BACKEND_URL}/stats", timeout=5.0)
            
            if response.status_code == 200:
                data = response.json()
                return f"""
### Statistics
- **Total chunks indexed:** {data.get('total_chunks', 0)}
- **Collection name:** {data.get('collection_name', 'N/A')}
"""
            else:
                return "❌ Failed to get statistics"
    except Exception as e:
        return f"❌ Error getting stats: {str(e)}"


async def clear_collection():
    """Clear all documents from the vector store."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(f"{BACKEND_URL}/clear", timeout=10.0)
            
            if response.status_code == 200:
                return "✅ All documents cleared from the vector store"
            else:
                return f"❌ Failed to clear collection: {response.text}"
    except Exception as e:
        return f"❌ Error clearing collection: {str(e)}"


# Create Gradio interface
with gr.Blocks(title="RAG System with NAS SMB", theme=gr.themes.Soft()) as app:
    gr.Markdown("# 🔍 RAG System with NAS SMB Support")
    gr.Markdown("Upload documents or ingest from NAS, then query using natural language powered by Llama 3.1")
    
    with gr.Tab("📤 Document Management"):
        gr.Markdown("### Upload Documents")
        gr.Markdown("Supported formats: `.pdf`, `.docx`, `.xlsx`, `.csv`, `.md`, `.txt`, `.drawio`")
        
        with gr.Row():
            with gr.Column():
                file_upload = gr.File(
                    label="Select files to upload",
                    file_count="multiple",
                    file_types=[".pdf", ".docx", ".xlsx", ".csv", ".md", ".txt", ".drawio"]
                )
                upload_btn = gr.Button("📤 Upload and Process", variant="primary")
                upload_output = gr.Textbox(label="Upload Status", lines=10)
        
        gr.Markdown("---")
        gr.Markdown("### Ingest from NAS")
        gr.Markdown("Process all documents from the mounted NAS share at `/docs`")
        
        with gr.Row():
            with gr.Column():
                ingest_nas_btn = gr.Button("🗂️ Ingest NAS Documents", variant="secondary")
                ingest_nas_output = gr.Textbox(label="NAS Ingestion Status", lines=3)
    
    with gr.Tab("💬 Query"):
        gr.Markdown("### Ask Questions")
        gr.Markdown("Query your documents using natural language")
        
        with gr.Row():
            with gr.Column(scale=3):
                query_input = gr.Textbox(
                    label="Your Question",
                    placeholder="What is the main topic discussed in the documents?",
                    lines=2
                )
                top_k_slider = gr.Slider(
                    minimum=1,
                    maximum=10,
                    value=5,
                    step=1,
                    label="Number of sources to retrieve"
                )
                query_btn = gr.Button("🔍 Ask", variant="primary")
            
        with gr.Row():
            with gr.Column():
                answer_output = gr.Textbox(label="Answer", lines=10)
            with gr.Column():
                sources_output = gr.Markdown(label="Sources")
    
    with gr.Tab("📊 System Info"):
        gr.Markdown("### System Status")
        
        with gr.Row():
            with gr.Column():
                health_btn = gr.Button("🏥 Check Backend Health")
                health_output = gr.Textbox(label="Health Status", lines=2)
        
        gr.Markdown("---")
        
        with gr.Row():
            with gr.Column():
                stats_btn = gr.Button("📊 Get Statistics")
                stats_output = gr.Markdown(label="Statistics")
        
        gr.Markdown("---")
        gr.Markdown("### ⚠️ Danger Zone")
        
        with gr.Row():
            with gr.Column():
                clear_btn = gr.Button("🗑️ Clear All Documents", variant="stop")
                clear_output = gr.Textbox(label="Clear Status", lines=2)
    
    # Wire up the event handlers
    upload_btn.click(fn=upload_documents, inputs=[file_upload], outputs=[upload_output])
    ingest_nas_btn.click(fn=ingest_nas_documents, inputs=[], outputs=[ingest_nas_output])
    query_btn.click(fn=query_documents, inputs=[query_input, top_k_slider], outputs=[answer_output, sources_output])
    health_btn.click(fn=check_backend_health, inputs=[], outputs=[health_output])
    stats_btn.click(fn=get_stats, inputs=[], outputs=[stats_output])
    clear_btn.click(fn=clear_collection, inputs=[], outputs=[clear_output])


if __name__ == "__main__":
    app.launch(
        server_name="0.0.0.0",
        server_port=3000,
        share=False
    )
