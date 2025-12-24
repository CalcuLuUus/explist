# GPU Task Scheduler

一个用于在 Ubuntu 服务器上管理 GPU 任务队列的前后端项目。后端基于 FastAPI，负责监控 GPU 状态、维护任务队列并通过 `tmux` 启动命令；前端基于 Vue (Vite)，提供 GPU 监控面板、任务列表与详情、实时 tmux 日志以及任务创建表单。前端开发服务器默认监听 `1895` 端口。

## 项目结构

```
backend/
  app/
    main.py           # FastAPI 应用入口
    task_manager.py   # 任务调度器，tmux 集成，SQLite 持久化
    gpu_monitor.py    # 调用 nvidia-smi 采集 GPU 信息
    schemas.py        # Pydantic 模型与枚举
  requirements.txt    # 后端依赖
  runtime/            # 运行期数据库、日志与脚本
frontend/
  package.json        # 前端依赖 & 脚本
  vite.config.js      # Vite 配置（含 /api 代理 & 1895 端口）
  src/                # Vue 组件与样式
README.md             # 本文件
```

## 环境要求

- Python 3.10+
- Node.js 18+
- `tmux` (后端用来运行任务)
- `nvidia-smi` (NVIDIA 驱动提供的工具，用于 GPU 监控)

## 后端启动

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 默认监听 8000，可以根据需要调整
# 若机器安装了 Conda，会自动尝试检测 ~/miniconda3 等路径。
# 也可通过 `CONDA_INIT_SCRIPT=/path/to/conda.sh` 明确指定初始化脚本。
uvicorn app.main:app --reload --port 8000
```

> 运行过程中会在 `backend/runtime/` 下生成 `tasks.db`、任务日志及脚本文件。

### 主要接口

- `GET /api/gpus`：当前设备的 GPU 列表以及占用情况。
- `GET /api/tasks`：任务队列与历史记录（按创建时间倒序）。
- `POST /api/tasks`：创建新任务（名称 / GPU 类型与数量 / bash 命令）。
- `GET /api/tasks/{task_id}`：单个任务详情（状态、分配 GPU、tmux 会话等）。
- `GET /api/tasks/{task_id}/logs`：任务 tmux 输出的最后 100 行。

后台调度器默认每 2 秒巡检一次：检查队列、尝试分配 GPU、监听 tmux 会话并回写任务状态与退出码。

## 前端启动

```bash
cd frontend
npm install
npm run dev
```

开发服务器会自动代理 `/api` 到 `http://localhost:8000`，并在 `http://localhost:1895` 提供界面：

- **GPU 状态**：展示每块 GPU 的利用率、显存占用、是否空闲及当前任务。
- **任务列表**：实时查看队列与历史任务，支持进入详情。
- **任务详情**：显示命令信息、GPU 分配、退出码，并每 3 秒拉取 tmux 日志的最后 100 行。
- **新建任务**：填写任务名称、选择 GPU 类型及数量、输入 bash 命令后提交。
  - 命令输入框支持多行脚本，可直接写 `source /path/to/conda.sh`、`conda activate <env>` 等指令来切换环境，系统会在 tmux shell 中按顺序执行。

## 运行建议

1. 先启动后端 `uvicorn`，确认 GPU 信息正常返回。
2. 前端 `npm run dev` 后访问 `http://localhost:1895`。
3. 创建任务时，命令将在新的 `tmux` 会话（如 `task_1`）中执行，日志实时写入 `backend/runtime/tasks/task_<id>/tmux.log`。
4. 若后端重启但 `tmux` 会话仍在运行，调度器会尝试恢复状态；缺失的会话将被标记为失败。

欢迎根据业务需要扩展功能，例如接入 WebSocket、完善权限与鉴权、支持自定义工作目录等。

--- 

## TODO List

### bug

- [ ] GPU状态读取

### feature

- [ ] 列表刷新
- [ ] 停止任务
