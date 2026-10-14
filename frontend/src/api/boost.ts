import { api } from './client';

export interface BoostTask {
  id: string;
  action: 'enable' | 'disable';
  tenant_id: number;
  instance_id: string;
  status: 'running' | 'success' | 'failed';
  message: string;
  public_ip: string | null;
  created_at: number;
}

/** 一键开启下行 500M（后台任务，返回 task_id 轮询） */
export async function enable500M(
  tenantId: number, instanceId: string, sshPort = 22,
): Promise<{ task_id: string }> {
  const resp = await api.post('/api/v1/boost/enable', {
    tenant_id: tenantId, instance_id: instanceId, ssh_port: sshPort,
  });
  return resp.data as { task_id: string };
}

/** 关闭下行 500M */
export async function disable500M(
  tenantId: number, instanceId: string, retainNatGw = false, retainNlb = false,
): Promise<{ task_id: string }> {
  const resp = await api.post('/api/v1/boost/disable', {
    tenant_id: tenantId, instance_id: instanceId,
    retain_nat_gw: retainNatGw, retain_nlb: retainNlb,
  });
  return resp.data as { task_id: string };
}

/** 500M 任务状态 */
export async function getBoostTask(taskId: string): Promise<BoostTask> {
  const resp = await api.get(`/api/v1/boost/tasks/${taskId}`);
  return resp.data as BoostTask;
}
