<template>
  <div>
    <div class="card">
      <div class="section-title">
        <h2>任务详情 · #{{ task?.id ?? taskId }}</h2>
        <div>
          <button class="btn secondary" type="button" @click="$emit('back')">返回列表</button>
        </div>
      </div>
      <div v-if="error" class="empty-state">
        {{ error }}
      </div>
      <div v-else-if="loading" class="empty-state">加载中…</div>
      <div v-else-if="!task" class="empty-state">
        未找到任务信息。
      </div>
      <div v-else class="task-detail">
        <div class="grid">
          <div class="stat-card">
            <h3>状态</h3>
            <strong>{{ statusLabel(task.status) }}</strong>
          </div>
          <div class="stat-card">
            <h3>GPU 需求</h3>
            <strong>{{ task.gpu_type }} × {{ task.gpu_count }}</strong>
          </div>
          <div class="stat-card">
            <h3>分配 GPU</h3>
            <strong>{{ task.assigned_gpus.length ? task.assigned_gpus.join(', ') : '未分配' }}</strong>
          </div>
          <div class="stat-card">
            <h3>退出码</h3>
            <strong>{{ task.exit_code ?? '未知' }}</strong>
          </div>
        </div>
        <div class="details-grid">
          <div>
            <h3>基本信息</h3>
            <p><strong>名称：</strong>{{ task.name }}</p>
            <p><strong>创建时间：</strong>{{ formatDate(task.created_at) }}</p>
            <p><strong>开始时间：</strong>{{ formatDate(task.started_at) }}</p>
            <p><strong>完成时间：</strong>{{ formatDate(task.completed_at) }}</p>
            <p><strong>tmux 会话：</strong>{{ task.tmux_session ?? '尚未启动' }}</p>
            <p v-if="task.error" style="color: #c0262d">
              <strong>错误：</strong>{{ task.error }}
            </p>
          </div>
          <div>
            <h3>命令</h3>
            <pre class="logs-viewer"><code>{{ task.command }}</code></pre>
          </div>
        </div>
      </div>
    </div>
    <div class="card" style="margin-top: 1.5rem">
      <div class="section-title">
        <h2>tmux 输出</h2>
        <div>
          <span class="muted">每 3 秒刷新一次</span>
          <button class="btn secondary" type="button" @click="refreshLogs" :disabled="logsLoading">
            {{ logsLoading ? '刷新中…' : '刷新日志' }}
          </button>
        </div>
      </div>
      <div v-if="logsError" class="empty-state">
        {{ logsError }}
      </div>
      <div v-else class="logs-viewer">
        <pre><code>{{ logs.join('\n') }}</code></pre>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue';
import { fetchTask, fetchTaskLogs } from '../api';

const props = defineProps({
  taskId: {
    type: Number,
    required: true,
  },
});

defineEmits(['back']);

const task = ref(null);
const loading = ref(false);
const error = ref('');

const logs = ref([]);
const logsLoading = ref(false);
const logsError = ref('');

let detailIntervalId = null;
let logIntervalId = null;

const statusLabel = (status) => {
  switch (status) {
    case 'queued':
      return '排队中';
    case 'running':
      return '执行中';
    case 'completed':
      return '已完成';
    case 'failed':
      return '失败';
    default:
      return status;
  }
};

const formatDate = (value) => {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
};

const refreshDetail = async () => {
  if (!props.taskId) return;
  loading.value = true;
  error.value = '';
  try {
    task.value = await fetchTask(props.taskId);
  } catch (err) {
    error.value = err?.response?.data?.detail ?? err.message ?? '加载任务失败';
  } finally {
    loading.value = false;
  }
};

const refreshLogs = async () => {
  if (!props.taskId) return;
  logsLoading.value = true;
  logsError.value = '';
  try {
    const response = await fetchTaskLogs(props.taskId, 100);
    logs.value = response.lines ?? [];
  } catch (err) {
    logsError.value = err?.response?.data?.detail ?? err.message ?? '读取日志失败';
  } finally {
    logsLoading.value = false;
  }
};

const clearIntervals = () => {
  if (detailIntervalId) clearInterval(detailIntervalId);
  if (logIntervalId) clearInterval(logIntervalId);
};

const setupIntervals = () => {
  clearIntervals();
  detailIntervalId = setInterval(refreshDetail, 5000);
  logIntervalId = setInterval(refreshLogs, 3000);
};

watch(
  () => props.taskId,
  async () => {
    await refreshDetail();
    await refreshLogs();
    setupIntervals();
  },
  { immediate: true }
);
onBeforeUnmount(clearIntervals);
</script>

<style scoped>
.task-detail {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.details-grid {
  display: grid;
  gap: 1.5rem;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
}
</style>
