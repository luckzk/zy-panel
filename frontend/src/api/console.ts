import { api } from './client';

/** 串行控制台连接（后端 /api/v1/console/*） */
export interface ConsoleConnection {
  id: number;
  tenant_id: number;
  instance_id: string;
  instance_name: string;
  connection_ocid: string;
  region: string;
  state: 'CREATING' | 'ACTIVE' | 'FAILED';
  error: string;
  created_at: string | null;
}

/** 创建串行控制台连接（真实 OCI 调用，后台等待 ACTIVE） */
export async function createConsoleConnection(
  tenant_id: number,
  instance_id: string,
  instance_name?: string,
): Promise<ConsoleConnection> {
  const resp = await api.post('/api/v1/console/connections', {
    tenant_id,
    instance_id,
    instance_name: instance_name || '',
  });
  return resp.data as ConsoleConnection;
}

/** 查询串行控制台连接 */
export async function listConsoleConnections(
  tenant_id: number,
  instance_id?: string,
): Promise<ConsoleConnection[]> {
  const resp = await api.get('/api/v1/console/connections', {
    params: { tenant_id, instance_id: instance_id || undefined },
  });
  return (resp.data?.items ?? []) as ConsoleConnection[];
}

/** 删除串行控制台连接 */
export async function deleteConsoleConnection(tenant_id: number, conn_id: number): Promise<void> {
  await api.delete(`/api/v1/console/connections/${conn_id}`, { params: { tenant_id } });
}

/** 串口自动重置系统密码任务 */
export interface ResetPasswordTask {
  task_id: string;
  state: 'running' | 'success' | 'failed';
  step: string;
  logs: string[];
  error: string;
  created_at: string;
}

/** 发起串口自动重置系统密码（后台任务，需二次确认：会硬重启实例） */
export async function startResetPassword(
  tenant_id: number,
  instance_id: string,
  instance_name: string,
  username: string,
  new_password: string,
): Promise<string> {
  const resp = await api.post('/api/v1/console/reset-password', {
    tenant_id,
    instance_id,
    instance_name,
    username,
    new_password,
  });
  return resp.data.task_id as string;
}

/** 查询改密码任务状态 */
export async function getResetPasswordTask(task_id: string): Promise<ResetPasswordTask> {
  const resp = await api.get(`/api/v1/console/reset-password/tasks/${task_id}`);
  return resp.data as ResetPasswordTask;
}
