from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


class GPUQueryError(RuntimeError):
    """Raised when GPU information cannot be collected."""


@dataclass
class GPUState:
    index: int
    name: str
    memory_total: Optional[int] = None
    memory_used: Optional[int] = None
    utilization_gpu: Optional[int] = None
    utilization_mem: Optional[int] = None


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
    command = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.total,memory.used,utilization.gpu,utilization.memory",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=5
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
        if len(parts) < 2:
            logger.debug("Unexpected nvidia-smi line format: %s", line)
            continue

        index = _parse_int(parts[0])
        name = parts[1]
        if index is None:
            logger.debug("Missing GPU index in line=%s", line)
            continue

        memory_total = _parse_int(parts[2]) if len(parts) > 2 else None
        memory_used = _parse_int(parts[3]) if len(parts) > 3 else None
        utilization_gpu = _parse_int(parts[4]) if len(parts) > 4 else None
        utilization_mem = _parse_int(parts[5]) if len(parts) > 5 else None
        states.append(
            GPUState(
                index=index,
                name=name,
                memory_total=memory_total,
                memory_used=memory_used,
                utilization_gpu=utilization_gpu,
                utilization_mem=utilization_mem,
            )
        )
    return states

