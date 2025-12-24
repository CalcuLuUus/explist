<template>
  <div class="card">
    <div class="section-title">
      <h2>新建任务</h2>
      <p class="muted">填写任务信息后提交，自动进入队列。</p>
    </div>
    <form @submit.prevent="handleSubmit">
      <label>
        任务名称
        <input v-model="form.name" type="text" placeholder="如：模型训练 #1" required />
      </label>
      <label>
        GPU 类型
        <select v-model="form.gpu_type" required>
          <option value="" disabled>请选择 GPU 类型</option>
          <option v-for="option in gpuOptions" :key="option" :value="option">
            {{ option }}
          </option>
        </select>
      </label>
      <label>
        GPU 数量
        <input
          v-model.number="form.gpu_count"
          type="number"
          min="1"
          :max="maxGpuCount"
          required
        />
      </label>
      <label>
        Bash 命令
        <textarea
          v-model="form.command"
          placeholder="例如：python train.py --epochs 10"
          required
        ></textarea>
      </label>
      <div v-if="error" style="color: #c0262d">{{ error }}</div>
      <div style="display: flex; gap: 1rem">
        <button class="btn" type="submit" :disabled="submitting || !form.gpu_type">
          {{ submitting ? '创建中…' : '创建任务' }}
        </button>
        <button class="btn secondary" type="button" @click="resetForm" :disabled="submitting">
          重置
        </button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { reactive, ref, watch } from 'vue';
import { createTask } from '../api';

const props = defineProps({
  gpuOptions: {
    type: Array,
    default: () => [],
  },
  maxGpuCount: {
    type: Number,
    default: 8,
  },
  prefillTask: {
    type: Object,
    default: null,
  },
});

const emit = defineEmits(['created']);

const form = reactive({
  name: '',
  gpu_type: '',
  gpu_count: 1,
  command: '',
});

const submitting = ref(false);
const error = ref('');

const applyPrefill = (prefill) => {
  if (!prefill) return;
  form.name = prefill.name ?? '';
  if (prefill.gpu_type && props.gpuOptions.includes(prefill.gpu_type)) {
    form.gpu_type = prefill.gpu_type;
  } else if (!form.gpu_type) {
    form.gpu_type = props.gpuOptions[0] ?? '';
  }
  form.gpu_count = prefill.gpu_count ?? 1;
  form.command = prefill.command ?? '';
};

const resetForm = () => {
  error.value = '';
  if (props.prefillTask) {
    applyPrefill(props.prefillTask);
    return;
  }
  form.name = '';
  form.gpu_type = props.gpuOptions[0] ?? '';
  form.gpu_count = 1;
  form.command = '';
};

watch(
  () => props.gpuOptions,
  (options) => {
    if (!options.length) {
      form.gpu_type = '';
      return;
    }
    if (!options.includes(form.gpu_type)) {
      form.gpu_type = options[0];
    }
  },
  { immediate: true }
);

watch(
  () => props.prefillTask,
  (prefill) => {
    if (prefill) {
      applyPrefill(prefill);
    }
  },
  { immediate: true }
);

const handleSubmit = async () => {
  if (!form.gpu_type) {
    error.value = '请选择 GPU 类型';
    return;
  }
  submitting.value = true;
  error.value = '';
  try {
    const task = await createTask({
      name: form.name.trim(),
      gpu_type: form.gpu_type,
      gpu_count: form.gpu_count,
      command: form.command.trim(),
    });
    emit('created', task);
    resetForm();
  } catch (err) {
    error.value = err?.response?.data?.detail ?? err.message ?? '任务创建失败';
  } finally {
    submitting.value = false;
  }
};
</script>
