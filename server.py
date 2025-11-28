"""FastAPI server for the Real-time Dashboard."""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import List

import pandas as pd
from fastapi import FastAPI, UploadFile, WebSocket, WebSocketDisconnect, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from pipeline import ProcessingPipeline, PipelineResult
from tts_generate import _resolve_column

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles

# Ensure audio directory exists for StaticFiles
Path("audio").mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory="audio"), name="audio")

pipeline = ProcessingPipeline(output_dir="audio")

class TestStats(BaseModel):
    total_items: int
    processed_items: int
    avg_latency: float
    avg_score: float
    success_rate: float

from constants import TAIWAN_ANIMALS

import json

CONFIG_FILE = Path("config.json")

def load_config():
    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            LOGGER.error(f"Failed to load config: {e}")
    return {
        "phrase_hints": list(TAIWAN_ANIMALS),
        "stt_provider": "google"
    }

def save_config(config_data):
    try:
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        LOGGER.error(f"Failed to save config: {e}")

# Initialize state from file
_init_config = load_config()
current_phrase_hints: List[str] = _init_config.get("phrase_hints", list(TAIWAN_ANIMALS))
current_stt_provider: str = _init_config.get("stt_provider", "google")
current_results: List[PipelineResult] = []

class ConfigUpdate(BaseModel):
    phrase_hints: List[str]
    stt_provider: str = "google"

@app.get("/config")
async def get_config():
    return {"phrase_hints": current_phrase_hints, "stt_provider": current_stt_provider}

@app.post("/config")
async def update_config(config: ConfigUpdate):
    global current_phrase_hints, current_stt_provider
    current_phrase_hints = config.phrase_hints
    current_stt_provider = config.stt_provider
    
    save_config({
        "phrase_hints": current_phrase_hints,
        "stt_provider": current_stt_provider
    })
    
    return {"message": "Config updated", "phrase_hints": current_phrase_hints, "stt_provider": current_stt_provider}

@app.post("/upload")
def upload_csv(
    file: UploadFile,
    id_col: str = Form(None),
    question_col: str = Form(None),
    answer_col: str = Form(None),
    stt_provider: str = Form("google")
):
    """Upload a CSV file to start a new test run."""
    global current_results, current_stt_provider
    current_results = []
    
    print(f"DEBUG: Upload request received. Provider: {stt_provider}")
    LOGGER.info(f"Upload request: id_col='{id_col}', q_col='{question_col}', ans_col='{answer_col}', provider='{stt_provider}'")

    # Update provider if sent with upload
    if stt_provider:
        current_stt_provider = stt_provider
    
    try:
        temp_path = Path("temp_upload.csv")
        print(f"DEBUG: Saving file to {temp_path.absolute()}")
        with temp_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        print("DEBUG: File saved successfully")
            
        # Parse CSV to get items
        print("DEBUG: Reading CSV with pandas")
        df = pd.read_csv(temp_path)
        df = df.fillna("") # Replace NaN with empty string to avoid JSON errors
        print(f"DEBUG: CSV read. Columns: {df.columns.tolist()}")
        # Normalize columns: strip whitespace and convert full-width parentheses to half-width
        df.columns = [
            str(col).strip().replace("（", "(").replace("）", ")") 
            for col in df.columns
        ]
        LOGGER.info(f"Normalized CSV Columns: {df.columns.tolist()}")
        
        # Normalize user inputs as well
        if id_col: id_col = id_col.replace("（", "(").replace("）", ")")
        if question_col: question_col = question_col.replace("（", "(").replace("）", ")")
        if answer_col: answer_col = answer_col.replace("（", "(").replace("）", ")")
        
        # Resolve columns
        final_id_col = id_col if id_col and id_col in df.columns else _resolve_column(df.columns.tolist(), "id", "id")
        final_q_col = question_col if question_col and question_col in df.columns else _resolve_column(df.columns.tolist(), "zh_question", "question")
        
        final_ans_col = None
        if answer_col and answer_col in df.columns:
            final_ans_col = answer_col
        else:
            # Try to find answer column
            try:
                final_ans_col = _resolve_column(df.columns.tolist(), "Ans-ch", "Ans-ch")
            except ValueError:
                pass
                
            if not final_ans_col:
                # Fallback search
                for col in df.columns:
                    if "Ans" in col or "回答" in col:
                        final_ans_col = col
                        break
        
        LOGGER.info(f"Resolved columns: id='{final_id_col}', q='{final_q_col}', ans='{final_ans_col}'")

        items = []
        for _, row in df.iterrows():
            items.append({
                "id": row[final_id_col],
                "question": row[final_q_col],
                "reference_answer": row[final_ans_col] if final_ans_col else ""
            })
            
        return {
            "message": "File uploaded", 
            "item_count": len(items), 
            "items": items,
            "columns": df.columns.tolist(),
            "detected_mapping": {
                "id": final_id_col,
                "question": final_q_col,
                "answer": final_ans_col
            },
            "stt_provider": current_stt_provider
        }
    except Exception as e:
        LOGGER.exception("Error processing upload")
        return JSONResponse(status_code=400, content={"message": str(e)})

@app.websocket("/ws/test")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        items = data.get("items", [])
        
        if not items:
            await websocket.send_json({"type": "error", "message": "No items to process"})
            return

        total = len(items)
        processed = 0
        total_score = 0
        total_latency = 0
        
        for item in items:
            # Determine language based on provider
            # This logic could be more sophisticated or user-configurable
            language_code = "en-US" if current_stt_provider == "openai" else "zh-TW"
            
            # Process item
            res = pipeline.process_item(
                item_id=item["id"],
                question=item["question"],
                reference_answer=item["reference_answer"],
                phrase_hints=current_phrase_hints,
                stt_provider=current_stt_provider,
                language_code=language_code
            )
            
            # Update stats
            processed += 1
            if res.status == "success":
                total_score += res.score
                total_latency += res.total_latency
            
            current_results.append(res)
            
            # Send update
            audio_url = None
            if res.audio_path:
                if res.audio_path.startswith("http"):
                    audio_url = res.audio_path
                else:
                    audio_url = f"/audio/{Path(res.audio_path).name}"

            await websocket.send_json({
                "type": "update",
                "result": {
                    "id": res.id,
                    "audio_url": audio_url,
                    "question": res.question,
                    "stt_text": res.stt_text,
                    "ai_answer": res.ai_answer,
                    "score": res.score,
                    "latency": res.total_latency,
                    "breakdown": {
                        "tts": res.tts_latency,
                        "stt": res.stt_latency,
                        "chatbase": res.chatbase_latency,
                        "eval": res.eval_latency
                    },
                    "status": res.status,
                    "error": res.error_msg
                },
                "stats": {
                    "processed": processed,
                    "total": total,
                    "avg_score": total_score / processed if processed else 0,
                    "avg_latency": total_latency / processed if processed else 0
                }
            })
            
            # Small delay to yield control if needed, though pipeline is sync blocking mostly
            await asyncio.sleep(0.01)
            
        await websocket.send_json({"type": "complete"})
        
    except WebSocketDisconnect:
        LOGGER.info("Client disconnected")
    except Exception as e:
        LOGGER.exception("WebSocket error")
        await websocket.send_json({"type": "error", "message": str(e)})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
