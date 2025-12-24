<template>
  <div class="card">
    <div class="section-title">
      <h2>GPU 状态</h2>
      <div>
        <span class="muted" v-if="lastUpdated">
          最近更新：{{ formattedUpdated }}
        </span>
        <button class="btn secondary" type="button" @click="$emit('refresh')" :disabled="loading">
          {{ loading ? '刷新中…' : '手动刷新' }}
        </button>
      </div>
    </div>
    <div v-if="error" class="empty-state">
      {{ error }}
    </div>
    <div v-else-if="gpus.length === 0" class="empty-state">
      暂未检测到可用 GPU。
    </div>
    <div v-else>
      <div class="grid">
        <div v-for="gpu in gpus" :key="gpu.index" class="stat-card">
          <h3>#{{ gpu.index }} · {{ gpu.name }}</h3>
          <strong>{{ gpu.is_free ? '空闲' : '占用' }}</strong>
          <div class="muted">
            显存：{{ gpu.memory_used ?? 'N/A' }} / {{ gpu.memory_total ?? 'N/A' }} MiB
          </div>
          <div class="muted">利用率：{{ gpu.utilization_gpu ?? 'N/A' }}%</div>
          <div class="muted">任务：{{ gpu.assigned_task_id ?? '无' }}</div>
          <div class="muted">
            <template v-if="gpu.processes?.length">
              使用者：
              <span
                v-for="(proc, index) in gpu.processes"
                :key="`${gpu.index}-${proc.pid}-${index}`"
                class="process-pill"
              >
                {{ formatProcess(proc) }}
              </span>
            </template>
            <template v-else> 使用者：无 </template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  gpus: {
    type: Array,
    default: () => [],
  },
  loading: {
    type: Boolean,
    default: false,
  },
  lastUpdated: {
    type: [String, Date, null],
    default: null,
  },
  error: {
    type: String,
    default: '',
  },
});

const formattedUpdated = computed(() => {
  if (!props.lastUpdated) return '';
  const date = typeof props.lastUpdated === 'string' ? new Date(props.lastUpdated) : props.lastUpdated;
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString();
});

const formatProcess = (proc) => {
  if (!proc) return '';
  const parts = [];
  if (proc.username) parts.push(proc.username);
  if (proc.name) parts.push(proc.name);
  if (proc.pid) parts.push(`#${proc.pid}`);
  return parts.join(' · ');
};
</script>
