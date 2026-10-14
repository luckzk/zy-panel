import { api } from './client';

/** 后端定时任务 */
export interface ScheduledTask {
  id: number;
  tenant_id: number;
  name: string;
  task_type: string;
  task_type_name: string;
  instance_id: string;
  cron_expr: string;
  enabled: boolean;
  last_run_at: string | null;
  last_status: 'success' | 'failed' | null;
  last_error: string | null;
  next_run_at: string | null;
  created_at: string | null;
  updated_at?: string | null;
  exec_result?: { ok: boolean; msg: string };
}

export interface ScheduledTaskCreate {
  tenant_id: number;
  name: string;
  task_type: string;
  instance_id: string;
  cron_expr: string;
  enabled?: boolean;
}

export interface ScheduledTaskUpdate {
  name?: string;
  task_type?: string;
  instance_id?: string;
  cron_expr?: string;
  enabled?: boolean;
}

export interface TaskTypeOption {
  value: string;
  label: string;
}

/** 任务列表 */
export async function listScheduledTasks(): Promise<ScheduledTask[]> {
  const resp = await api.get('/api/v1/scheduled-tasks');
  return (resp.data ?? []) as ScheduledTask[];
}

/** 支持的任务类型 */
export async function getTaskTypes(): Promise<TaskTypeOption[]> {
  const resp = await api.get('/api/v1/scheduled-tasks/task-types');
  return (resp.data ?? []) as TaskTypeOption[];
}

export async function createScheduledTask(body: ScheduledTaskCreate): Promise<ScheduledTask> {
  const resp = await api.post('/api/v1/scheduled-tasks', body);
  return resp.data as ScheduledTask;
}

export async function updateScheduledTask(id: number, body: ScheduledTaskUpdate): Promise<ScheduledTask> {
  const resp = await api.put(`/api/v1/scheduled-tasks/${id}`, body);
  return resp.data as ScheduledTask;
}

export async function deleteScheduledTask(id: number): Promise<void> {
  await api.delete(`/api/v1/scheduled-tasks/${id}`);
}

export async function toggleScheduledTask(id: number, enabled: boolean): Promise<ScheduledTask> {
  const resp = await api.post(`/api/v1/scheduled-tasks/${id}/toggle`, { enabled });
  return resp.data as ScheduledTask;
}

/** 立即执行一次 */
export async function runScheduledTaskNow(id: number): Promise<ScheduledTask> {
  const resp = await api.post(`/api/v1/scheduled-tasks/${id}/run-now`);
  return resp.data as ScheduledTask;
}
