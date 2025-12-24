# GPU Task Scheduler 技术说明

## 1. 技术栈概览

| 层级 | 技术 | 说明 |
| ---- | ---- | ---- |
| 后端 | Python 3.10+, FastAPI, Pydantic, SQLite, `tmux`, `nvidia-smi` | FastAPI 提供 REST API；Pydantic 校验请求/响应；SQLite 落地任务状态；`tmux` 隔离任务执行；`nvidia-smi` 获取 GPU 信息。 |
| 前端 | Vite + Vue 3 + Axios | Vite 提供开发构建；Vue 3 组合式 API 构建组件；Axios 调用后端 REST API。 |
| 其他 | `tee`、`python`、`conda`、`bash` | 任务脚本通过 tmux 运行 `bash`，并用 `tee` 把 stdout/stderr 同步到 tmux 窗口和日志文件。 |

## 2. 后端结构与流程

### 2.1 目录结构 (backend/)
```
app/
  main.py           # FastAPI 入口
  task_manager.py   # 任务调度器：队列、tmux、SQLite
  gpu_monitor.py    # 调用 nvidia-smi
  schemas.py        # Pydantic 模型
runtime/
  tasks.db          # SQLite 数据库
  tasks/task_<id>/  # 每个任务的 run.sh/command.sh/log
```

### 2.2 `app/main.py`
- 初始化 FastAPI，配置 CORS（允许 `http://localhost:1895` 等）。
- 创建 `TaskManager` 对象（传入 `db_path`, `runtime_dir`, `poll_interval`）。
- 定义 REST API：
  - `GET /api/health`: `{status: "ok"}`。
  - `GET /api/gpus`: 返回当前 GPU 列表（`List[GPUInfo]`）。
  - `GET /api/tasks`: 返回所有任务摘要。
  - `POST /api/tasks`: 创建任务，输入 `TaskCreate`。
  - `GET /api/tasks/{task_id}`: 任务详情。
  - `GET /api/tasks/{task_id}/logs`: 读取日志尾部 100 行。
  - `POST /api/tasks/{task_id}/cancel`: 中断任务（队列/运行都支持）。

### 2.3 `app/schemas.py`
- `TaskStatus` 枚举：`queued | running | completed | failed | cancelled`。
- `GPUInfo` 字段：index/name/memory/utilization/assigned_task_id/is_free。
- `TaskCreate`: `name, gpu_type, gpu_count, command`。
- `TaskSummary/TaskDetail`: 在 `TaskDetail` 中增补 command / assigned_gpus / tmux_session / exit_code / error。
- `TaskLogResponse`: `task_id, lines, truncated`。

### 2.4 `app/gpu_monitor.py`
- `query_gpu_states()`：
  - 运行 `nvidia-smi --query-gpu=index,uuid,...`。
  - 解析 CSV，每行生成 `GPUState`（index, uuid, name, memory, utilization）。
  - 如果 `nvidia-smi` 不可用或失败，记录 warning 并返回空列表 / raise `GPUQueryError`。
- `_query_gpu_processes()`（可扩展）：查询 GPU 上的进程信息（未默认启用）。

### 2.5 `TaskManager` 核心逻辑
#### 2.5.1 核心属性
- `_queue`: `collections.deque`，存排队任务 ID。
- `_running`: 运行中任务字典：`task_id -> RunningTask`。
- `_conn`: SQLite 连接（`sqlite3.connect(check_same_thread=False)`）。
- `_state_lock`、`_db_lock`: 控制并发访问。
- `_thread`: 调度线程；`_stop_event` 控制退出。

#### 2.5.2 API 方法
- `create_task(payload: TaskCreate) -> TaskDetail`
  - 调 `_safe_query_gpu_states()` 验证 `payload.gpu_type`。
  - 插入 SQLite `tasks` 表，状态 `queued`。
  - `self._queue.append(task_id)`。
- `list_tasks() -> List[TaskSummary]`
- `get_task(task_id) -> TaskDetail`
- `get_gpu_status() -> List[GPUInfo]`
  - 合并 nvidia-smi 与 `_running`/SQLite 中记录的 assigned_gpus。
- `get_task_logs(task_id, tail=100)`
  - 打开 `log_path`，读取行保存到 `deque(maxlen=tail)`，返回 `TaskLogResponse`。
- `cancel_task(task_id)`
  - 若状态 queued：从 `_queue` 移除并标记 `cancelled`。
  - 若 running：`tmux kill-session` 并更新状态 `cancelled`。

#### 2.5.3 调度循环
```python
def _scheduler_loop(self):
    while not stop:
        gpu_states = _safe_query_gpu_states()
        with _state_lock:
            _launch_tasks_if_possible(gpu_states)
            _refresh_running_tasks()
        wait(poll_interval)
```

#### 2.5.4 `_launch_tasks_if_possible(gpu_states)`
1. 计算 `_running` 中占用的 GPU index，避免重复使用。
2. 按 `state.name`（GPU 型号）分类可用 GPU。
3. FIFO 从 `_queue` 取任务：
   - 如果可用 GPU 数量不够，break（保留 head-of-line）。
   - 否则调用 `_start_task(row, assigned)`：
     - 在 `runtime/tasks/task_<id>/` 生成 `command.sh` 和 `run.sh`。
     - `command.sh`：用户命令（多行），开头/结尾打印 PATH、`command -v python/conda` 等。
     - `run.sh`：
       ```bash
       #!/usr/bin/env bash
       set -eo pipefail
       VENV_BIN=<workdir>/.venv/bin
       SYSTEM_PYTHON=/usr/bin/python3 (fallback)
       # 用 SYSTEM_PYTHON 去掉 PATH 中的 .venv/bin
       PATH=$( $SYSTEM_PYTHON - <<'PY' ... )
       export PATH
       export LOG_FILE=.../tmux.log
       export PYTHONUNBUFFERED=1   # 确保 stdout 实时输出
       echo "===== Scheduler Environment =====" >> "$LOG_FILE"
       bash "$COMMAND_SCRIPT" 2>&1 | tee -a "$LOG_FILE"
       exit_code=${PIPESTATUS[0]}
       echo $exit_code > exit_code
       exit $exit_code
       ```
     - 通过 `tmux new-session -d -s task_<id> run.sh` 启动。
   - 更新 SQLite (`status=running, started_at, tmux_session, assigned_gpus, log_path`)。
   - `_running[task_id] = RunningTask(...)`。
4. 失败时（tmux 启动错误等）标记任务 `failed` 并跳过。

#### 2.5.5 `_refresh_running_tasks`
- 遍历 `_running`，检查 `tmux has-session` 返回值。
- 如果 session 不存在：
  - 读取 `exit_code`（文件中第一行数字）。
  - `exit_code == 0` -> `completed`，否则 `failed` 并记录 `error`。
  - 调 `_update_task_completion` 写入 SQLite（状态、完成时间、退出码、错误信息）。
  - `_running.pop(task_id)`。

#### 2.5.6 日志/环境输出
- `run.sh` 及 `command.sh` 都会在日志中输出：
  ```
  ===== Scheduler Environment =====
  Timestamp...
  PATH: ...
  Python on PATH: ...
  ===== Command Script Start =====
  Script PATH: ...
  command -v python: ...
  command -v conda: ...
  ...
  ===== Command Script Exit =====
  PATH: ...
  python -> ...
  ```
  方便定位 PATH/环境问题。

---

## 3. 前端组件与交互

### 3.1 目录结构 (frontend/)
```
src/
  api.js             # Axios 调用封装
  App.vue            # 顶层视图
  main.js            # Vue 挂载
  styles.css         # 全局样式
  components/
    GpuStatusPanel.vue
    TaskList.vue
    TaskDetail.vue
    NewTaskForm.vue
```

### 3.2 `src/api.js`
```js
const client = axios.create({ baseURL: '/api', timeout: 10000 });

export const fetchGpus = () => client.get('/gpus');
export const fetchTasks = () => client.get('/tasks');
export const fetchTask = (id) => client.get(`/tasks/${id}`);
export const fetchTaskLogs = (id, tail = 100) => client.get(`/tasks/${id}/logs`, { params: { tail } });
export const createTask = (payload) => client.post('/tasks', payload);
export const cancelTask = (id) => client.post(`/tasks/${id}/cancel`);
```

### 3.3 `App.vue`
- 管理视图/状态：
  - `currentView`: `gpus` / `tasks` / `taskDetail` / `newTask`。
  - `selectedTaskId`: 当前详情任务 ID。
  - `taskPrefill`: “复制任务”预填数据。
  - `gpuState`, `taskState`: 包含 `items`, `loading`, `error`, `updatedAt`。
- 生命周期：
  - `onMounted` -> `refreshGpu()` + `refreshTasks()` -> `setupIntervals()`（5s 轮询）。
  - `onBeforeUnmount` -> `clearIntervals()`。
- 交互：
  - “GPU 状态”按钮 -> `showGpus()`。
  - “任务列表”按钮 -> `showTasks()`。
  - “新建任务”按钮 -> `showNewTask()`（同时清空 `taskPrefill`）。
  - TaskList `view-task` -> `openTaskDetail(taskId)`。
  - TaskDetail `back` -> `showTasks()`。
  - TaskDetail `clone(taskData)` -> `taskPrefill = {...taskData}; currentView = 'newTask';`。
  - NewTaskForm `created(task)` -> 跳转任务详情并刷新列表。

### 3.4 `GpuStatusPanel.vue`
- 展示 GPU 卡片：
  - `#index · name`，`空闲/占用`，显存、利用率、任务 ID。
  - 输入：
    - `gpus`: GPUInfo 数组。
    - `loading`, `lastUpdated`, `error`。
- 提供“手动刷新”按钮，调用父组件 `refreshGpu`。

### 3.5 `TaskList.vue`
- 表格列：ID、名称、状态、GPU 类型、GPU 数量、创建时间、详情按钮。
- `status-pill` 显示中文状态（排队中/执行中/已完成/失败/已中断）。
- 空状态提示：加载错误/无任务。

### 3.6 `TaskDetail.vue`
- 状态展示：
  - 上方卡片：状态、GPU 需求、已分配 GPU、退出码。
  - 下方信息：名称、创建/开始/完成时间、tmux 会话、错误信息、命令文本。
- 操作按钮：
  - “返回列表”。
  - “复制任务”：触发 `clone`（表单预填）。
  - “中断任务”：调用 `cancelTask`（运行/排队都可），失败时显示错误消息。
- 日志视图：
  - `tmux.log` 输出，每 3 秒 `fetchTaskLogs(taskId)`。
  - “刷新日志”按钮手动触发。
- 数据刷新：
  - `watch(taskId)` -> 立即拉取详情 + 日志，并每 5 秒/3 秒设置轮询。
  - `detailRefreshing` 标记细粒度刷新，避免整块闪烁。

### 3.7 `NewTaskForm.vue`
- 表单字段：
  - `name`, `gpu_type`, `gpu_count`, `command`。
- 支持多行命令（可以 `source`/`conda activate`/`env` 等）。
- `prefillTask` 属性：
  - 如果来自“复制任务”，表单自动填入对应值。
  - “重置”按钮：若有预填就回到预填内容，否则清空。
- 提交：
  - `POST /api/tasks`，成功后触发 `created` 事件（父组件跳到详情）。
  - 出错时显示错误消息（后端 4xx/5xx 或网络错误）。

---

## 4. Pipeline 举例

1. **用户从前端提交**：
   ```bash
   source /home/calculus/miniconda3/etc/profile.d/conda.sh
   conda activate pt212
   cd /mnt/hugedisk/calculus/explist
   python test.py --num 10
   ```
2. **前端** `POST /api/tasks` -> TaskManager 创建任务（状态 queued）。
3. **调度**：
   - `TaskManager` 轮询 -> 检测到有空闲 GPU -> `_start_task`。
   - 生成 `run.sh`, `command.sh`，并写入日志头。
4. **执行**：
   - `tmux new-session` 运行 `run.sh`。
   - `run.sh` 取消 PATH 中 `.venv/bin`，导出 `PYTHONUNBUFFERED=1`，写入环境信息，然后 `bash command.sh | tee`。
   - `command.sh` 开头/结尾记录 PATH 和 `command -v python/conda`。
5. **日志**：
   - tmux 窗口和 `tmux.log` 同步输出，因此前端轮询日志可实时看到进度。
6. **结束**：
   - `run.sh` 退出后写 `exit_code` 文件。
   - `_refresh_running_tasks` 捕捉到 tmux session 不存在 -> 更新任务状态+退出码。
7. **前端刷新**：
   - “任务列表”每 5 秒刷新，状态随之更新。
   - “任务详情”每 5 秒刷新详情、3 秒刷新日志。

---

## 5. “复制任务”功能

- **触发**：在 TaskDetail 点击“复制任务”。
- **事件**：TaskDetail `emit('clone', {...taskInfo})`。
- **响应**：App.vue `cloneTask(taskData)`，将 `taskPrefill` 设置为该任务数据，切换到新建任务视图。
- **预填**：NewTaskForm `watch(prefillTask)` 自动填入 name/gpu_type/gpu_count/command。
- **提交**：用户如需修改可在表单调整，然后提交即生成一个相同配置的新任务。

---

## 6. 可迁移性 & 改进建议
1. **环境依赖**：默认继承 `.venv/bin`、`tmux`、`conda` 的路径，换用户或 systemd 启动时需重新配置 PATH。可考虑：
   - 把 tmux path / conda init script 抽象为配置文件。
   - 提供自检命令检测依赖是否存在。
2. **安全性**：命令框允许任意 shell 脚本；在共享环境应限制或容器化。
3. **调度可扩展性**：
   - 增加任务优先级、显存策略。
   - 更细粒度的错误处理（tmux/conda/nvidia-smi 错误提示）。
4. **日志/性能**：
   - 重复读取 `tmux.log` 效率较低，考虑 `seek/tail -n` 或 WebSocket。
5. **维护性**：
   - `task_manager.py` 可拆分成模块，方便单元测试。
   - 前端若持续扩展，可引入状态管理（Pinia/Vuex）。

---

## 7. 部署 & 使用注意事项
- 确保系统安装 `tmux` 与 NVIDIA 驱动（提供 `nvidia-smi`）。
- 后端默认使用 `backend/.venv`，但 `run.sh` 会自动剔除 `.venv/bin`，因此可安全执行 `conda activate ...`。
- 任务命令支持多行脚本，可直接写 `source /path/to/conda.sh`、`conda activate <env>`、`python ...`。
- 日志在 `backend/runtime/tasks/task_<id>/tmux.log`，前端会自动轮询显示。
- 若需要迁移到其他用户/机器，请更新命令中的绝对路径，并根据需要修改 `TaskManager` 提供的配置（如 `conda` 初始化脚本）。

---

以上文档描述了完整的技术栈、前后端工作流、任务调度 pipeline，以及“复制任务”等具体功能的输入输出和实现细节，便于在新环境中部署或二次开发。
