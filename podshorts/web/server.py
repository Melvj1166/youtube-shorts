from __future__ import annotations

import logging
import threading
import uuid
import shutil
from pathlib import Path
from typing import Dict, Any, List

from fastapi import FastAPI, BackgroundTasks, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from podshorts.config import Settings
from podshorts.pipeline import run_pipeline
from podshorts.utils.logging import get_logger

# Thread-safe task status registry
class TaskRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: Dict[str, Dict[str, Any]] = {}

    def get(self, video_id: str) -> Dict[str, Any]:
        with self._lock:
            return self._tasks.get(video_id, {"status": "idle", "progress": 0, "logs": [], "error": None, "shorts": []})

    def update(self, video_id: str, **kwargs):
        with self._lock:
            if video_id not in self._tasks:
                self._tasks[video_id] = {
                    "status": "idle",
                    "progress": 0,
                    "logs": [],
                    "error": None,
                    "shorts": []
                }
            self._tasks[video_id].update(kwargs)

    def add_log(self, video_id: str, log_msg: str):
        with self._lock:
            if video_id not in self._tasks:
                self._tasks[video_id] = {
                    "status": "idle",
                    "progress": 0,
                    "logs": [],
                    "error": None,
                    "shorts": []
                }
            self._tasks[video_id]["logs"].append(log_msg)

task_registry = TaskRegistry()


class WebAppLogHandler(logging.Handler):
    def __init__(self, video_id: str):
        super().__init__()
        self.video_id = video_id

    def emit(self, record):
        msg = self.format(record)
        task_registry.add_log(self.video_id, msg)
        
        # Intercept messages to update high-level progress stages
        text = record.getMessage()
        if "Stage 1:" in text:
            task_registry.update(self.video_id, status="downloading", progress=10)
        elif "Stage 2:" in text:
            task_registry.update(self.video_id, status="heatmap", progress=20)
        elif "Stage 3:" in text:
            task_registry.update(self.video_id, status="transcribing", progress=30)
        elif "Stage 4:" in text:
            task_registry.update(self.video_id, status="segmenting", progress=50)
        elif "Stage 5:" in text:
            task_registry.update(self.video_id, status="scoring", progress=65)
        elif "Stage 6:" in text:
            task_registry.update(self.video_id, status="ranking", progress=75)
        elif "Stage 7:" in text:
            task_registry.update(self.video_id, status="face_tracking", progress=82)
        elif "Stage 8:" in text:
            task_registry.update(self.video_id, status="cropping", progress=88)
        elif "Stage 9:" in text:
            task_registry.update(self.video_id, status="subtitling", progress=93)
        elif "Stage 10:" in text:
            task_registry.update(self.video_id, status="exporting", progress=97)


class RunRequest(BaseModel):
    youtube_url: str
    top_n: int = 5
    force: bool = False


def execute_pipeline_task(video_id: str, input_url: str, settings: Settings):
    logger = get_logger("podshorts.pipeline")
    handler = WebAppLogHandler(video_id)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)-8s %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(handler)

    try:
        task_registry.update(video_id, status="starting", progress=5, error=None, logs=[])
        
        # Run standard pipeline
        output_dir = run_pipeline(input_url, settings)
        
        # Read final metadata
        metadata_file = output_dir / "metadata.json"
        import json
        metadata = {}
        if metadata_file.exists():
            with open(metadata_file, "r") as f:
                metadata = json.load(f)
        
        task_registry.update(
            video_id,
            status="completed",
            progress=100,
            shorts=metadata.get("shorts", []),
            title=metadata.get("title", video_id),
            uploader=metadata.get("uploader", "")
        )
    except Exception as exc:
        import traceback
        error_msg = str(exc)
        task_registry.add_log(video_id, f"ERROR: {error_msg}")
        task_registry.add_log(video_id, traceback.format_exc())
        task_registry.update(video_id, status="failed", progress=100, error=error_msg)
    finally:
        logger.removeHandler(handler)


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="PodShorts Local Web UI")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Ensure output and upload cache directories exist
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    upload_dir = settings.cache_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    # API Endpoint: List past successful runs
    @app.get("/api/history")
    def get_history():
        import json
        history = []
        if settings.output_dir.exists():
            for folder in sorted(settings.output_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if folder.is_dir():
                    metadata_file = folder / "metadata.json"
                    if metadata_file.exists():
                        try:
                            with open(metadata_file, "r") as f:
                                data = json.load(f)
                                history.append({
                                    "video_id": folder.name,
                                    "title": data.get("title", folder.name),
                                    "uploader": data.get("uploader", "Unknown"),
                                    "source_url": data.get("source_url", ""),
                                    "shorts_count": len(data.get("shorts", [])),
                                    "shorts": data.get("shorts", [])
                                })
                        except Exception:
                            pass
        return history

    # API Endpoint: Check pipeline status
    @app.get("/api/status/{video_id}")
    def get_status(video_id: str):
        state = task_registry.get(video_id)
        
        # Fallback: if task finished/idle but output files exist, populate completes
        if state["status"] == "idle":
            metadata_file = settings.output_dir / video_id / "metadata.json"
            if metadata_file.exists():
                import json
                try:
                    with open(metadata_file, "r") as f:
                        data = json.load(f)
                        task_registry.update(
                            video_id,
                            status="completed",
                            progress=100,
                            shorts=data.get("shorts", []),
                            title=data.get("title", video_id),
                            uploader=data.get("uploader", "")
                        )
                        state = task_registry.get(video_id)
                except Exception:
                    pass
        return state

    # API Endpoint: Run pipeline for YouTube URL
    @app.post("/api/run")
    def run_url(req: RunRequest, background_tasks: BackgroundTasks):
        url = req.youtube_url.strip()
        if not url:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")

        # Deduce video_id quickly
        video_id = ""
        if "watch?v=" in url:
            video_id = url.split("watch?v=")[1].split("&")[0]
        elif "youtu.be/" in url:
            video_id = url.split("youtu.be/")[1].split("?")[0]
        else:
            # Fallback to random unique ID if non-standard
            video_id = f"yt_{uuid.uuid4().hex[:10]}"

        # Strip safety
        video_id = "".join(c for c in video_id if c.isalnum() or c in ("-", "_"))

        state = task_registry.get(video_id)
        if state["status"] not in ("idle", "completed", "failed"):
            return {"video_id": video_id, "message": "Pipeline already active for this video"}

        # Clone current settings to override force
        run_settings = settings.model_copy(deep=True)
        run_settings.top_n_shorts = req.top_n
        run_settings.force_rerun = req.force

        background_tasks.add_task(
            execute_pipeline_task,
            video_id=video_id,
            input_url=url,
            settings=run_settings
        )

        return {"video_id": video_id, "status": "starting"}

    # API Endpoint: Upload local video
    @app.post("/api/upload")
    def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...), top_n: int = 5, force: bool = False):
        filename = file.filename
        if not filename or not filename.lower().endswith((".mp4", ".mov", ".mkv", ".avi")):
            raise HTTPException(status_code=400, detail="Invalid video file format. Supported: mp4, mov, mkv, avi")

        # Generate a unique video id
        safe_stem = "".join(c for c in Path(filename).stem if c.isalnum() or c in ("-", "_"))
        video_id = f"up_{safe_stem}_{uuid.uuid4().hex[:6]}"
        
        # Save file to a secure place in cache
        dest_path = upload_dir / f"{video_id}{Path(filename).suffix}"
        
        try:
            with dest_path.open("wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {e}")

        # Override configurations
        run_settings = settings.model_copy(deep=True)
        run_settings.top_n_shorts = top_n
        run_settings.force_rerun = force

        # Start background pipeline using the saved local file path!
        background_tasks.add_task(
            execute_pipeline_task,
            video_id=video_id,
            input_url=str(dest_path),
            settings=run_settings
        )

        return {"video_id": video_id, "status": "starting"}

    # Mount static paths
    app.mount("/output", StaticFiles(directory=str(settings.output_dir)), name="output")
    
    static_folder = Path(__file__).parent / "static"
    if static_folder.exists():
        app.mount("/static", StaticFiles(directory=str(static_folder)), name="static")

        # Default route serves index.html
        @app.get("/")
        def serve_index():
            from fastapi.responses import FileResponse
            return FileResponse(static_folder / "index.html")

    return app
