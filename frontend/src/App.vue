<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="brand">GPU 任务调度平台</div>
      <nav class="nav">
        <button :class="{ active: currentView === 'gpus' }" @click="showGpus">GPU 状态</button>
        <button :class="{ active: currentView === 'tasks' || currentView === 'taskDetail' }" @click="showTasks">
          任务列表
        </button>
        <button :class="{ active: currentView === 'newTask' }" @click="showNewTask">新建任务</button>
      </nav>
    </header>
    <main class="app-content">
      <GpuStatusPanel
        v-if="currentView === 'gpus'"
        :gpus="gpuState.items"
        :loading="gpuState.loading"
        :last-updated="gpuState.updatedAt"
        :error="gpuState.error"
        @refresh="refreshGpu"
      />
      <TaskList
        v-else-if="currentView === 'tasks'"
        :tasks="taskState.items"
        :loading="taskState.loading"
        :error="taskState.error"
        @view-task="openTaskDetail"
        @refresh="refreshTasks"
      />
      <TaskDetail
        v-else-if="currentView === 'taskDetail' && selectedTaskId"
        :task-id="selectedTaskId"
        @back="showTasks"
      />
      <div v-else-if="currentView === 'taskDetail'" class="card empty-state">
        请选择一个任务查看详情。
      </div>
      <NewTaskForm
        v-else-if="currentView === 'newTask'"
        :gpu-options="gpuTypes"
        @created="handleTaskCreated"
      />
    </main>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { fetchGpus, fetchTasks } from './api';
import GpuStatusPanel from './components/GpuStatusPanel.vue';
import TaskList from './components/TaskList.vue';
import TaskDetail from './components/TaskDetail.vue';
import NewTaskForm from './components/NewTaskForm.vue';

const currentView = ref('gpus');
const selectedTaskId = ref(null);

const gpuState = reactive({
  items: [],
  loading: false,
  error: '',
  updatedAt: null,
});

const taskState = reactive({
  items: [],
  loading: false,
  error: '',
  updatedAt: null,
});

let gpuIntervalId = null;
let taskIntervalId = null;

const refreshGpu = async () => {
  gpuState.loading = true;
  gpuState.error = '';
  try {
    const data = await fetchGpus();
    gpuState.items = data;
    gpuState.updatedAt = new Date().toISOString();
  } catch (err) {
    gpuState.error = err?.response?.data?.detail ?? err.message ?? 'GPU 数据获取失败';
  } finally {
    gpuState.loading = false;
  }
};

const refreshTasks = async () => {
  taskState.loading = true;
  taskState.error = '';
  try {
    const data = await fetchTasks();
    taskState.items = data;
    taskState.updatedAt = new Date().toISOString();
  } catch (err) {
    taskState.error = err?.response?.data?.detail ?? err.message ?? '任务数据获取失败';
  } finally {
    taskState.loading = false;
  }
};

const setupIntervals = () => {
  clearIntervals();
  gpuIntervalId = setInterval(refreshGpu, 5000);
  taskIntervalId = setInterval(refreshTasks, 5000);
};

const clearIntervals = () => {
  if (gpuIntervalId) clearInterval(gpuIntervalId);
  if (taskIntervalId) clearInterval(taskIntervalId);
};

onMounted(async () => {
  await Promise.all([refreshGpu(), refreshTasks()]);
  setupIntervals();
});

onBeforeUnmount(clearIntervals);

const showGpus = () => {
  currentView.value = 'gpus';
};

const showTasks = () => {
  currentView.value = 'tasks';
};

const showNewTask = () => {
  currentView.value = 'newTask';
};

const openTaskDetail = (taskId) => {
  selectedTaskId.value = taskId;
  currentView.value = 'taskDetail';
};

const handleTaskCreated = (task) => {
  selectedTaskId.value = task.id;
  currentView.value = 'taskDetail';
  refreshTasks();
};

const gpuTypes = computed(() => {
  const set = new Set(gpuState.items.map((gpu) => gpu.name));
  return Array.from(set);
});
</script>
