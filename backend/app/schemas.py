from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GPUInfo(BaseModel):
    index: int
    name: str
    memory_total: Optional[int] = Field(None, description="Total memory in MiB")
    memory_used: Optional[int] = Field(None, description="Used memory in MiB")
    utilization_gpu: Optional[int] = Field(None, description="GPU utilization percentage")
    utilization_mem: Optional[int] = Field(None, description="Memory utilization percentage")
    assigned_task_id: Optional[int] = Field(
        None, description="Active task id assigned by the scheduler, if any"
    )
    is_free: bool = Field(..., description="Whether the scheduler currently considers it idle")


class TaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    gpu_type: str = Field(..., min_length=1, max_length=120)
    gpu_count: int = Field(..., ge=1, le=8)
    command: str = Field(..., min_length=1)


class TaskSummary(BaseModel):
    id: int
    name: str
    status: TaskStatus
    gpu_type: str
    gpu_count: int
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


class TaskDetail(TaskSummary):
    command: str
    tmux_session: Optional[str]
    assigned_gpus: List[int]
    log_path: Optional[str]
    exit_code: Optional[int]
    error: Optional[str]


class TaskLogResponse(BaseModel):
    task_id: int
    lines: List[str]
    truncated: bool = False

