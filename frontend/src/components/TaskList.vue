<template>
  <div class="card">
    <div class="section-title">
      <h2>任务队列</h2>
      <div>
        <span class="muted">自动每 5 秒刷新</span>
        <button class="btn secondary" type="button" @click="$emit('refresh')" :disabled="loading">
          {{ loading ? '刷新中…' : '手动刷新' }}
        </button>
      </div>
    </div>
    <div v-if="error" class="empty-state">
      {{ error }}
    </div>
    <div v-else-if="tasks.length === 0" class="empty-state">
      当前没有任务，创建新任务试试。
    </div>
    <div v-else class="table-responsive">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>名称</th>
            <th>状态</th>
            <th>GPU 类型</th>
            <th>GPU 数量</th>
            <th>创建时间</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in tasks" :key="task.id">
            <td>{{ task.id }}</td>
            <td>{{ task.name }}</td>
            <td>
              <span class="status-pill" :class="statusClass(task.status)">
                {{ statusLabel(task.status) }}
              </span>
            </td>
            <td>{{ task.gpu_type }}</td>
            <td>{{ task.gpu_count }}</td>
            <td>{{ formatDate(task.created_at) }}</td>
            <td>
              <button class="btn secondary" type="button" @click="$emit('view-task', task.id)">
                详情
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  tasks: {
    type: Array,
    default: () => [],
  },
  loading: {
    type: Boolean,
    default: false,
  },
  error: {
    type: String,
    default: '',
  },
});

const statusClass = (status) => {
  switch (status) {
    case 'queued':
      return 'status-queued';
    case 'running':
      return 'status-running';
    case 'completed':
      return 'status-completed';
    case 'failed':
      return 'status-failed';
    case 'cancelled':
      return 'status-cancelled';
    default:
      return '';
  }
};

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
    case 'cancelled':
      return '已中断';
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
</script>
