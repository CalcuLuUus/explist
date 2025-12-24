from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from .schemas import GPUInfo, TaskCreate, TaskDetail, TaskLogResponse, TaskStatus, TaskSummary
from .task_manager import TaskManager

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="GPU Task Scheduler",
        version="1.0.0",
    )

    frontend_origins = [
        "http://localhost:1895",
        "http://127.0.0.1:1895",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=frontend_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    runtime_root = Path(__file__).resolve().parent.parent / "runtime"
    conda_activate = os.environ.get("CONDA_INIT_SCRIPT")
    if conda_activate:
        conda_activate_path = Path(conda_activate)
    else:
        conda_activate_path = None

    task_manager = TaskManager(
        db_path=runtime_root / "tasks.db",
        runtime_dir=runtime_root / "tasks",
        poll_interval=2.0,
        conda_activate_script=conda_activate_path,
    )

    def get_manager() -> TaskManager:
        return task_manager

    @app.on_event("startup")
    def _startup() -> None:
        logger.info("Starting task manager")
        task_manager.start()

    @app.on_event("shutdown")
    def _shutdown() -> None:
        logger.info("Stopping task manager")
        task_manager.stop()

    @app.get("/api/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/gpus", response_model=List[GPUInfo], tags=["gpus"])
    def list_gpus(manager: TaskManager = Depends(get_manager)) -> List[GPUInfo]:
        return manager.get_gpu_status()

    @app.get("/api/tasks", response_model=List[TaskSummary], tags=["tasks"])
    def list_tasks(manager: TaskManager = Depends(get_manager)) -> List[TaskSummary]:
        return manager.list_tasks()

    @app.post(
        "/api/tasks",
        response_model=TaskDetail,
        status_code=status.HTTP_201_CREATED,
        tags=["tasks"],
    )
    def create_task(payload: TaskCreate, manager: TaskManager = Depends(get_manager)) -> TaskDetail:
        try:
            return manager.create_task(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    @app.get("/api/tasks/{task_id}", response_model=TaskDetail, tags=["tasks"])
    def get_task(task_id: int, manager: TaskManager = Depends(get_manager)) -> TaskDetail:
        try:
            return manager.get_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.get("/api/tasks/{task_id}/logs", response_model=TaskLogResponse, tags=["tasks"])
    def get_task_logs(task_id: int, manager: TaskManager = Depends(get_manager)) -> TaskLogResponse:
        try:
            return manager.get_task_logs(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    @app.post("/api/tasks/{task_id}/cancel", response_model=TaskDetail, tags=["tasks"])
    def cancel_task(task_id: int, manager: TaskManager = Depends(get_manager)) -> TaskDetail:
        try:
            return manager.cancel_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return app


app = create_app()
