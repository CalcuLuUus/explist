from __future__ import annotations

import json
import logging
import os
import shlex
import sqlite3
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional

from subprocess import CalledProcessError, run

from .gpu_monitor import GPUQueryError, GPUState, query_gpu_states
from .schemas import GPUInfo, TaskCreate, TaskDetail, TaskLogResponse, TaskStatus, TaskSummary

logger = logging.getLogger(__name__)


@dataclass
class RunningTask:
    task_id: int
    session_name: str
    assigned_gpus: List[int]
    log_path: Path
    script_path: Path
    exit_code_path: Path
    started_at: datetime


class TaskManager:
    def __init__(self, db_path: Path, runtime_dir: Path, poll_interval: float = 2.0) -> None:
        self.db_path = Path(db_path)
        self.runtime_dir = Path(runtime_dir)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.poll_interval = poll_interval
        self.workdir = Path.cwd()

        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._db_lock = threading.RLock()

        self._queue: Deque[int] = deque()
        self._running: Dict[int, RunningTask] = {}
        self._state_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._ensure_tables()

    # --------------------------------------------------------------------- #
    # Lifecycle                                                             #
    # --------------------------------------------------------------------- #
    def start(self) -> None:
        with self._state_lock:
            self._load_initial_state()
        if self._thread is None:
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
            self._thread.start()
            logger.info("Task scheduler thread started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self.poll_interval * 2)
        self._thread = None
        logger.info("Task scheduler thread stopped")

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #
    def create_task(self, payload: TaskCreate) -> TaskDetail:
        gpu_states = self._safe_query_gpu_states()
        available_types = {state.name for state in gpu_states}
        if not available_types:
            raise ValueError("No GPUs detected on this host")
        if payload.gpu_type not in available_types:
            raise ValueError(f"GPU type '{payload.gpu_type}' not detected on this host")

        now = self._utc_now()
        with self._db_lock:
            cursor = self._conn.execute(
                """
                INSERT INTO tasks (name, gpu_type, gpu_count, command, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.name,
                    payload.gpu_type,
                    payload.gpu_count,
                    payload.command,
                    TaskStatus.QUEUED.value,
                    now.isoformat(),
                ),
            )
            task_id = int(cursor.lastrowid)
            self._conn.commit()

        with self._state_lock:
            self._queue.append(task_id)

        return self.get_task(task_id)

    def list_tasks(self) -> List[TaskSummary]:
        rows = self._fetch_rows(
            """
            SELECT id, name, status, gpu_type, gpu_count, created_at, started_at, completed_at
            FROM tasks
            ORDER BY created_at DESC
            """
        )
        return [self._row_to_summary(row) for row in rows]

    def get_task(self, task_id: int) -> TaskDetail:
        row = self._fetch_one(
            """
            SELECT id, name, status, gpu_type, gpu_count, command, created_at, started_at,
                   completed_at, tmux_session, assigned_gpus, log_path, exit_code, error
            FROM tasks
            WHERE id = ?
            """,
            (task_id,),
        )
        if row is None:
            raise KeyError(f"Task {task_id} not found")
        return self._row_to_detail(row)

    def get_gpu_status(self) -> List[GPUInfo]:
        gpu_states = self._safe_query_gpu_states()
        assigned_lookup: Dict[int, int] = {}
        with self._state_lock:
            for rt in self._running.values():
                for gpu_idx in rt.assigned_gpus:
                    assigned_lookup[gpu_idx] = rt.task_id
        infos: List[GPUInfo] = []
        for state in gpu_states:
            infos.append(
                GPUInfo(
                    index=state.index,
                    name=state.name,
                    memory_total=state.memory_total,
                    memory_used=state.memory_used,
                    utilization_gpu=state.utilization_gpu,
                    utilization_mem=state.utilization_mem,
                    assigned_task_id=assigned_lookup.get(state.index),
                    is_free=state.index not in assigned_lookup,
                )
            )
        return infos

    def get_task_logs(self, task_id: int, tail: int = 100) -> TaskLogResponse:
        detail = self.get_task(task_id)
        if not detail.log_path:
            return TaskLogResponse(task_id=task_id, lines=[], truncated=False)
        log_path = Path(detail.log_path)
        if not log_path.exists():
            return TaskLogResponse(task_id=task_id, lines=[], truncated=False)

        lines: Deque[str] = deque(maxlen=tail)
        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as fp:
                for line in fp:
                    lines.append(line.rstrip("\n"))
        except OSError as exc:
            raise RuntimeError(f"Failed to read log file for task {task_id}: {exc}") from exc
        truncated = False
        if tail and len(lines) == tail:
            truncated = True
        return TaskLogResponse(task_id=task_id, lines=list(lines), truncated=truncated)

    # --------------------------------------------------------------------- #
    # Internal helpers                                                      #
    # --------------------------------------------------------------------- #
    def _scheduler_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                gpu_states = self._safe_query_gpu_states()
                with self._state_lock:
                    self._launch_tasks_if_possible(gpu_states)
                    self._refresh_running_tasks()
            except Exception:
                logger.exception("Unexpected error inside scheduler loop")
            self._stop_event.wait(self.poll_interval)

    def _launch_tasks_if_possible(self, gpu_states: List[GPUState]) -> None:
        if not self._queue:
            return

        assigned_indices = {
            idx for task in self._running.values() for idx in task.assigned_gpus
        }

        available_by_type: Dict[str, List[GPUState]] = {}
        for state in gpu_states:
            if state.index in assigned_indices:
                continue
            available_by_type.setdefault(state.name, []).append(state)

        launched_any = True
        while self._queue and launched_any:
            launched_any = False
            task_id = self._queue[0]
            row = self._fetch_one(
                """
                SELECT id, name, status, gpu_type, gpu_count, command
                FROM tasks
                WHERE id = ?
                """,
                (task_id,),
            )
            if row is None:
                self._queue.popleft()
                continue

            gpu_type = row["gpu_type"]
            candidates = available_by_type.get(gpu_type, [])
            if len(candidates) < row["gpu_count"]:
                # Head-of-line block; wait for GPUs freeing up
                break

            assigned = [gpu.index for gpu in candidates[: row["gpu_count"]]]
            try:
                running = self._start_task(row, assigned)
            except Exception as exc:
                logger.exception("Failed to launch task %s: %s", task_id, exc)
                self._update_task_status(
                    task_id,
                    TaskStatus.FAILED,
                    error=f"Failed to launch task: {exc}",
                )
                self._queue.popleft()
                continue

            # Consume GPUs from available pool
            available_by_type[gpu_type] = candidates[row["gpu_count"] :]
            self._queue.popleft()
            self._running[task_id] = running
            launched_any = True

    def _start_task(self, row: sqlite3.Row, assigned_gpus: List[int]) -> RunningTask:
        task_id = int(row["id"])
        task_dir = self.runtime_dir / f"task_{task_id}"
        task_dir.mkdir(parents=True, exist_ok=True)
        log_path = task_dir / "tmux.log"
        exit_code_path = task_dir / "exit_code"
        script_path = task_dir / "run.sh"

        assigned_str = ",".join(str(idx) for idx in assigned_gpus)
        command = row["command"]

        script_lines = [
            "#!/usr/bin/env bash",
            "set -uo pipefail",
        ]
        if assigned_str:
            script_lines.append(f"export CUDA_VISIBLE_DEVICES={assigned_str}")
        script_lines.append(f"cd {shlex.quote(str(self.workdir))}")
        script_lines.append(command)
        script_lines.append("exit_code=$?")
        script_lines.append(f"echo $exit_code > \"{exit_code_path}\"")
        script_lines.append("exit $exit_code")

        script_path.write_text("\n".join(script_lines) + "\n", encoding="utf-8")
        os.chmod(script_path, 0o750)
        log_path.touch(exist_ok=True)

        session_name = f"task_{task_id}"
        self._ensure_tmux_available()

        launch_cmd = [
            "tmux",
            "new-session",
            "-d",
            "-s",
            session_name,
            str(script_path),
        ]
        try:
            run(launch_cmd, check=True)
            pipe_cmd = [
                "tmux",
                "pipe-pane",
                "-t",
                session_name,
                "-o",
                f"cat >> {shlex.quote(str(log_path))}",
            ]
            run(pipe_cmd, check=True)
        except CalledProcessError as exc:
            raise RuntimeError(f"tmux command failed: {exc}") from exc

        started_at = self._utc_now()
        with self._db_lock:
            self._conn.execute(
                """
                UPDATE tasks
                SET status = ?, started_at = ?, tmux_session = ?, assigned_gpus = ?, log_path = ?
                WHERE id = ?
                """,
                (
                    TaskStatus.RUNNING.value,
                    started_at.isoformat(),
                    session_name,
                    json.dumps(assigned_gpus),
                    str(log_path),
                    task_id,
                ),
            )
            self._conn.commit()

        logger.info(
            "Launched task %s in tmux session %s with GPUs %s",
            task_id,
            session_name,
            assigned_gpus,
        )

        return RunningTask(
            task_id=task_id,
            session_name=session_name,
            assigned_gpus=assigned_gpus,
            log_path=log_path,
            script_path=script_path,
            exit_code_path=exit_code_path,
            started_at=started_at,
        )

    def _refresh_running_tasks(self) -> None:
        if not self._running:
            return

        completed: List[int] = []
        for task_id, running in list(self._running.items()):
            if self._tmux_has_session(running.session_name):
                continue

            exit_code = self._read_exit_code(running.exit_code_path)
            status = TaskStatus.COMPLETED if exit_code == 0 else TaskStatus.FAILED
            error_message = None
            if exit_code is None:
                status = TaskStatus.FAILED
                error_message = "Task terminated without reporting an exit code"
            elif exit_code != 0:
                error_message = f"Process exited with status {exit_code}"
            self._update_task_completion(task_id, status, exit_code, error_message)
            completed.append(task_id)

        for task_id in completed:
            self._running.pop(task_id, None)

    def _update_task_status(
        self,
        task_id: int,
        status: TaskStatus,
        *,
        error: Optional[str] = None,
    ) -> None:
        with self._db_lock:
            self._conn.execute(
                """
                UPDATE tasks
                SET status = ?, error = ?
                WHERE id = ?
                """,
                (status.value, error, task_id),
            )
            self._conn.commit()

    def _update_task_completion(
        self,
        task_id: int,
        status: TaskStatus,
        exit_code: Optional[int],
        error: Optional[str],
    ) -> None:
        completed_at = self._utc_now()
        with self._db_lock:
            self._conn.execute(
                """
                UPDATE tasks
                SET status = ?, completed_at = ?, exit_code = ?, error = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    completed_at.isoformat(),
                    exit_code,
                    error,
                    task_id,
                ),
            )
            self._conn.commit()
        logger.info("Task %s finished with status %s", task_id, status.value)

    def _ensure_tables(self) -> None:
        with self._db_lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    gpu_type TEXT NOT NULL,
                    gpu_count INTEGER NOT NULL,
                    command TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    tmux_session TEXT,
                    assigned_gpus TEXT,
                    log_path TEXT,
                    exit_code INTEGER,
                    error TEXT
                )
                """
            )
            self._conn.commit()

    def _load_initial_state(self) -> None:
        rows = self._fetch_rows(
            """
            SELECT id, status, tmux_session, assigned_gpus
            FROM tasks
            WHERE status IN (?, ?)
            ORDER BY created_at ASC
            """,
            (TaskStatus.QUEUED.value, TaskStatus.RUNNING.value),
        )
        for row in rows:
            task_id = int(row["id"])
            status = TaskStatus(row["status"])
            if status == TaskStatus.QUEUED:
                self._queue.append(task_id)
                continue

            session = row["tmux_session"]
            assigned = json.loads(row["assigned_gpus"] or "[]")
            if session and self._tmux_has_session(session):
                running = RunningTask(
                    task_id=task_id,
                    session_name=session,
                    assigned_gpus=assigned,
                    log_path=self.runtime_dir / f"task_{task_id}" / "tmux.log",
                    script_path=self.runtime_dir / f"task_{task_id}" / "run.sh",
                    exit_code_path=self.runtime_dir / f"task_{task_id}" / "exit_code",
                    started_at=self._utc_now(),
                )
                self._running[task_id] = running
            else:
                self._update_task_completion(
                    task_id,
                    TaskStatus.FAILED,
                    exit_code=None,
                    error="tmux session missing after restart",
                )

    def _fetch_rows(self, query: str, params: tuple = ()) -> List[sqlite3.Row]:
        with self._db_lock:
            cursor = self._conn.execute(query, params)
            rows = cursor.fetchall()
        return rows

    def _fetch_one(self, query: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        with self._db_lock:
            cursor = self._conn.execute(query, params)
            row = cursor.fetchone()
        return row

    def _row_to_summary(self, row: sqlite3.Row) -> TaskSummary:
        return TaskSummary(
            id=int(row["id"]),
            name=row["name"],
            status=TaskStatus(row["status"]),
            gpu_type=row["gpu_type"],
            gpu_count=int(row["gpu_count"]),
            created_at=self._parse_dt(row["created_at"]),
            started_at=self._parse_dt(row["started_at"]),
            completed_at=self._parse_dt(row["completed_at"]),
        )

    def _row_to_detail(self, row: sqlite3.Row) -> TaskDetail:
        assigned = json.loads(row["assigned_gpus"] or "[]")
        return TaskDetail(
            id=int(row["id"]),
            name=row["name"],
            status=TaskStatus(row["status"]),
            gpu_type=row["gpu_type"],
            gpu_count=int(row["gpu_count"]),
            command=row["command"],
            created_at=self._parse_dt(row["created_at"]),
            started_at=self._parse_dt(row["started_at"]),
            completed_at=self._parse_dt(row["completed_at"]),
            tmux_session=row["tmux_session"],
            assigned_gpus=[int(idx) for idx in assigned],
            log_path=row["log_path"],
            exit_code=row["exit_code"],
            error=row["error"],
        )

    def _tmux_has_session(self, session_name: str) -> bool:
        result = run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True,
        )
        return result.returncode == 0

    def _read_exit_code(self, path: Path) -> Optional[int]:
        if not path.exists():
            return None
        try:
            content = path.read_text().strip()
            if not content:
                return None
            return int(content)
        except (OSError, ValueError) as exc:
            logger.debug("Failed to read exit code from %s: %s", path, exc)
            return None

    def _parse_dt(self, value: Optional[str]) -> Optional[datetime]:
        if value is None:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _ensure_tmux_available(self) -> None:
        result = run(["tmux", "-V"], capture_output=True)
        if result.returncode != 0:
            raise RuntimeError("tmux is required but not available on this system")

    def _safe_query_gpu_states(self) -> List[GPUState]:
        try:
            return query_gpu_states()
        except GPUQueryError as exc:
            logger.warning("GPU query failed: %s", exc)
            return []
