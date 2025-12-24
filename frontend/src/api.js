import axios from 'axios';

const client = axios.create({
  baseURL: '/api',
  timeout: 10000,
});

export async function fetchGpus() {
  const { data } = await client.get('/gpus');
  return data;
}

export async function fetchTasks() {
  const { data } = await client.get('/tasks');
  return data;
}

export async function fetchTask(taskId) {
  const { data } = await client.get(`/tasks/${taskId}`);
  return data;
}

export async function fetchTaskLogs(taskId, tail = 100) {
  const { data } = await client.get(`/tasks/${taskId}/logs`, {
    params: { tail },
  });
  return data;
}

export async function createTask(payload) {
  const { data } = await client.post('/tasks', payload);
  return data;
}

export async function cancelTask(taskId) {
  const { data } = await client.post(`/tasks/${taskId}/cancel`);
  return data;
}
