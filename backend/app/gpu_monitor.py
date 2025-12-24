from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class GPUQueryError(RuntimeError):
    """Raised when GPU information cannot be collected."""


@dataclass
class GPUState:
    index: int
    name: str
    uuid: Optional[str] = None
    memory_total: Optional[int] = None
    memory_used: Optional[int] = None
    utilization_gpu: Optional[int] = None
    utilization_mem: Optional[int] = None
    processes: List["GPUProcess"] = field(default_factory=list)


@dataclass
class GPUProcess:
    pid: int
    name: str
    used_memory: Optional[int] = None
    username: Optional[str] = None


def _parse_int(value: str) -> Optional[int]:
    value = value.strip()
    if not value or value == "N/A":
        return None
    try:
        return int(float(value))
    except ValueError:
        logger.debug("Failed to parse integer GPU metric from value=%s", value)
        return None


def query_gpu_states() -> List[GPUState]:
    """
    Query GPU state via nvidia-smi.

    Returns an empty list if nvidia-smi is unavailable. Raises GPUQueryError for
    unexpected failures.
    """
    gpu_command = [
        "nvidia-smi",
        "--query-gpu=index,uuid,name,memory.total,memory.used,utilization.gpu,utilization.memory",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            gpu_command, capture_output=True, text=True, check=False, timeout=5
        )
    except FileNotFoundError as exc:
        logger.warning("nvidia-smi not found on PATH: %s", exc)
        return []
    except subprocess.SubprocessError as exc:
        raise GPUQueryError(f"Failed to invoke nvidia-smi: {exc}") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "NVIDIA" in stderr or stderr:
            raise GPUQueryError(f"nvidia-smi returned non-zero exit status: {stderr}")
        return []

    lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    states: List[GPUState] = []
    for line in lines:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            logger.debug("Unexpected nvidia-smi line format: %s", line)
            continue

        index = _parse_int(parts[0])
        uuid = parts[1] if len(parts) > 1 else None
        name = parts[2]
        if index is None:
            logger.debug("Missing GPU index in line=%s", line)
            continue

        memory_total = _parse_int(parts[3]) if len(parts) > 3 else None
        memory_used = _parse_int(parts[4]) if len(parts) > 4 else None
        utilization_gpu = _parse_int(parts[5]) if len(parts) > 5 else None
        utilization_mem = _parse_int(parts[6]) if len(parts) > 6 else None
        states.append(
            GPUState(
                index=index,
                uuid=uuid,
                name=name,
                memory_total=memory_total,
                memory_used=memory_used,
                utilization_gpu=utilization_gpu,
                utilization_mem=utilization_mem,
            )
        )
    processes = _query_gpu_processes()
    if processes:
        states_by_uuid: Dict[str, GPUState] = {
            state.uuid: state for state in states if state.uuid
        }
        for gpu_uuid, process in processes:
            state = states_by_uuid.get(gpu_uuid)
            if state:
                state.processes.append(process)
    return states


def _query_gpu_processes() -> List[Tuple[str, GPUProcess]]:
    command = [
        "nvidia-smi",
        "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=5
        )
    except FileNotFoundError:
        return []
    except subprocess.SubprocessError as exc:
        logger.debug("Failed to query GPU processes: %s", exc)
        return []

    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        if "No running processes found" in output:
            return []
        logger.debug("GPU process query returned non-zero status: %s", output)
        return []

    lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    processes: List[Tuple[str, GPUProcess]] = []
    for line in lines:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        gpu_uuid = parts[0]
        pid = _parse_int(parts[1])
        if not gpu_uuid or pid is None:
            continue
        name = parts[2] if len(parts) > 2 else ""
        used_memory = _parse_int(parts[3]) if len(parts) > 3 else None
        username = _lookup_username(pid)
        processes.append(
            (gpu_uuid, GPUProcess(pid=pid, name=name, used_memory=used_memory, username=username))
        )
    return processes


def _lookup_username(pid: int) -> Optional[str]:
    try:
        result = subprocess.run(
            ["ps", "-o", "user=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except subprocess.SubprocessError:
        return None
    if result.returncode != 0:
        return None
    username = result.stdout.strip()
    return username or None
