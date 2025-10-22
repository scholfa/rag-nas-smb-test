import os
import gradio as gr
import httpx
import uuid
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


# upload_documents removed — ingestion is only supported from NAS


async def ingest_nas_documents():
    """Trigger NAS document ingestion. Returns (status_message, task_id)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(f"{BACKEND_URL}/ingest/nas")

            if response.status_code in (200, 201):
                data = response.json()
                task_id = data.get("task_id")
                if task_id:
                    return f"✅ NAS ingestion started (task_id={task_id})", task_id
                return f"✅ NAS ingestion started", ""
            else:
                # try to surface JSON detail if present
                try:
                    err = response.json().get("detail", response.text)
                except Exception:
                    err = response.text
                return f"❌ NAS ingestion failed: {err}", ""
    except Exception as e:
        return f"❌ Error triggering NAS ingestion: {str(e)}", ""


async def query_documents(query: str, top_k: int, temperature: float, max_tokens: int):
    """Query the RAG system. Generates a request_id and returns (answer, sources_text, request_id)."""
    if not query or query.strip() == "":
        return "❌ Please enter a question", "", ""

    request_id = str(uuid.uuid4())

    try:
        payload = {
            "query": query,
            "top_k": top_k,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "request_id": request_id
        }

        async with httpx.AsyncClient(timeout=600.0) as client:
            response = await client.post(f"{BACKEND_URL}/query", json=payload)

            if response.status_code == 200:
                data = response.json()
                answer = data.get("answer", "No answer generated")
                sources = data.get("sources", [])

                sources_text = "\n\n### Sources:\n"
                for i, source in enumerate(sources, 1):
                    sources_text += f"\n**{i}. {source.get('path', 'unknown')}** (chunk {source.get('chunk', 0)})\n"
                    sources_text += f"```\n{source.get('preview', '')}\n```\n"

                return answer, sources_text, request_id
            elif response.status_code == 499:
                return "❌ Query aborted by client", "", request_id
            else:
                try:
                    error_detail = response.json().get("detail", response.text)
                except Exception:
                    error_detail = response.text
                return f"❌ Query failed: {error_detail}", "", request_id
    except Exception as e:
        return f"❌ Error querying: {str(e)}", "", request_id


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
    gr.Markdown("Upload documents or ingest from NAS, then query using natural language")
    
    with gr.Tab("📤 Document Management"):
        gr.Markdown("### Ingest from NAS")
        gr.Markdown("Process all documents from the mounted NAS share at `/docs`")
        
        with gr.Row():
            with gr.Column():
                ingest_nas_btn = gr.Button("🗂️ Ingest NAS Documents", variant="secondary")
                ingest_abort_btn = gr.Button("⛔ Abort Ingest", variant="stop")
                ingest_status_btn = gr.Button("ℹ️ Ingest Status")
                ingest_nas_output = gr.Textbox(label="NAS Ingestion Status", lines=3)
                ingest_task_id = gr.Textbox(visible=False)
    
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
                temperature_slider = gr.Slider(
                    minimum=0.0,
                    maximum=1.0,
                    value=0.0,
                    step=0.01,
                    label="Temperature (0=deterministic)"
                )
                max_tokens_slider = gr.Slider(
                    minimum=16,
                    maximum=1024,
                    value=256,
                    step=16,
                    label="Max tokens to generate"
                )
                query_btn = gr.Button("🔍 Ask", variant="primary")
                abort_query_btn = gr.Button("⛔ Abort Query", variant="stop")
            
        with gr.Row():
            with gr.Column():
                answer_output = gr.Textbox(label="Answer", lines=10)
            with gr.Column():
                sources_output = gr.Markdown(label="Sources")
                query_request_id = gr.Textbox(visible=False)
    
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
    ingest_nas_btn.click(fn=ingest_nas_documents, inputs=[], outputs=[ingest_nas_output, ingest_task_id])

    # Proper handlers that call backend endpoints for abort/status
    def _ingest_status_sync(task_id: str):
        import requests
        if not task_id:
            return "❌ No task_id provided"
        try:
            r = requests.get(f"{BACKEND_URL}/ingest/nas/status", params={"task_id": task_id}, timeout=5.0)
            if r.status_code == 200:
                data = r.json()
                return f"Task {task_id}: status={data.get('status')} result={data.get('result')}"
            return f"Failed to get status: {r.text}"
        except Exception as e:
            return f"Error getting status: {str(e)}"

    def _ingest_abort_sync(task_id: str):
        import requests
        if not task_id:
            return "❌ No task_id provided", ""
        try:
            r = requests.post(f"{BACKEND_URL}/ingest/nas/abort", params={"task_id": task_id}, timeout=5.0)
            if r.status_code == 200:
                return f"Ingest aborted (task_id={task_id})", ""
            return f"Failed to abort: {r.text}", task_id
        except Exception as e:
            return f"Error aborting ingest: {str(e)}", task_id

    ingest_status_btn.click(fn=_ingest_status_sync, inputs=[ingest_task_id], outputs=[ingest_nas_output])
    ingest_abort_btn.click(fn=_ingest_abort_sync, inputs=[ingest_task_id], outputs=[ingest_nas_output, ingest_task_id])

    query_btn.click(fn=query_documents, inputs=[query_input, top_k_slider, temperature_slider, max_tokens_slider], outputs=[answer_output, sources_output, query_request_id])
    abort_query_btn.click(fn=lambda rid: ("❌ No request_id provided", "") if not rid else (f"Abort requested for request_id={rid}", ""), inputs=[query_request_id], outputs=[answer_output, query_request_id])

    def _abort_query_sync(request_id: str):
        import requests
        if not request_id:
            return "❌ No request_id provided", ""
        try:
            r = requests.post(f"{BACKEND_URL}/query/abort", params={"request_id": request_id}, timeout=5.0)
            if r.status_code == 200:
                return f"Query aborted (request_id={request_id})", ""
            return f"Failed to abort query: {r.text}", request_id
        except Exception as e:
            return f"Error aborting query: {str(e)}", request_id

    abort_query_btn.click(fn=_abort_query_sync, inputs=[query_request_id], outputs=[answer_output, query_request_id])
    health_btn.click(fn=check_backend_health, inputs=[], outputs=[health_output])
    stats_btn.click(fn=get_stats, inputs=[], outputs=[stats_output])
    clear_btn.click(fn=clear_collection, inputs=[], outputs=[clear_output])


if __name__ == "__main__":
    app.launch(
        server_name="0.0.0.0",
        server_port=3000,
        share=False
    )
