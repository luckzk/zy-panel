import { api } from './client';

/** 后端换 IP 任务（snake_case） */
export interface IpTask {
  id: number;
  tenant_id: number;
  instance_id: string;
  preferred_cidrs: string[];
  update_dns: boolean;
  status: 'pending' | 'running' | 'success' | 'failed';
  old_ip: string | null;
  new_ip: string | null;
  attempts: number;
  max_retries: number;
  dns_updated: boolean;
  next_attempt_at: string | null;
  last_error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ChangeIpCreate {
  tenant_id: number;
  instance_id: string;
  preferred_cidrs: string[];
  update_dns: boolean;
  max_retries: number;
}

/** 发起换 IP 任务（后台 worker 真实执行） */
export async function createChangeIpTask(body: ChangeIpCreate): Promise<IpTask> {
  const resp = await api.post('/api/v1/network/change-ip', body);
  return resp.data as IpTask;
}

/** 换 IP 任务列表 */
export async function listChangeIpTasks(): Promise<IpTask[]> {
  const resp = await api.get('/api/v1/network/change-ip-tasks');
  return (resp.data ?? []) as IpTask[];
}

/** 取消换 IP 任务（仅 pending/running） */
export async function cancelChangeIpTask(id: number): Promise<void> {
  await api.post(`/api/v1/network/ip-tasks/${id}/cancel`);
}

/** 为实例主 VNIC 附加公网 IPv6（会自动打通 VCN/子网/路由/安全组） */
export async function attachIpv6(tenantId: number, instanceId: string): Promise<{ ip_address: string }> {
  const resp = await api.post('/api/v1/network/ipv6', { tenant_id: tenantId, instance_id: instanceId });
  return resp.data as { ip_address: string };
}
