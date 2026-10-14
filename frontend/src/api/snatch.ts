import { api } from './client';
import type { SnatchStatus, SnatchTask } from '../types';
import type { TenantOption } from './tenants';

/** 后端抢机任务（snake_case） */
interface BackendSnatchTask {
  id: number;
  tenant_id: number;
  name: string;
  shape: string;
  compartment_id: string;
  image_id: string;
  boot_volume_id: string;
  recent_logs: string[];
  subnet_id: string;
  availability_domain: string;
  availability_domains: string[];
  ocpus: number | null;
  memory_in_gbs: number | null;
  display_name: string;
  assign_public_ip: boolean;
  has_ssh_key: boolean;
  status: string;
  interval_sec: number;
  max_attempts: number;
  attempts: number;
  last_error: string | null;
  last_attempt_at: string | null;
  next_attempt_at: string | null;
  created_instance_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SnatchTaskCreate {
  tenant_id: number;
  name: string;
  shape: string;
  compartment_id: string;
  image_id: string;
  boot_volume_id?: string;
  subnet_id: string;
  availability_domain: string;
  availability_domains?: string[];
  ocpus?: number | null;
  memory_in_gbs?: number | null;
  display_name?: string;
  assign_public_ip?: boolean;
  ssh_public_key?: string | null;
  interval_sec?: number;
  max_attempts?: number;
}

const STATUS = ['pending', 'running', 'paused', 'success', 'failed'] as const;

/** 后端 -> 前端类型映射（需要租户表来补名称/region） */
function toTask(b: BackendSnatchTask, tenants: TenantOption[]): SnatchTask {
  const t = tenants.find((x) => x.id === b.tenant_id);
  return {
    id: String(b.id),
    name: b.name,
    tenant: t?.name ?? `#${b.tenant_id}`,
    region: t?.region ?? '',
    ad:
      b.availability_domains && b.availability_domains.length > 1
        ? `${b.availability_domains[0]} 等${b.availability_domains.length}个AD轮询`
        : b.availability_domain || '-',
    shape: b.shape,
    image: b.boot_volume_id ? `引导卷:${b.boot_volume_id.slice(-12)}` : (b.image_id || '-'),
    status: (STATUS as readonly string[]).includes(b.status) ? (b.status as SnatchStatus) : 'pending',
    attempts: b.attempts,
    intervalSec: b.interval_sec,
    recentLogs: Array.isArray(b.recent_logs) ? b.recent_logs : [],
    createdAt: b.created_at ? new Date(b.created_at).toLocaleString('zh-CN', { hour12: false }) : '-',
  };
}

/** 任务列表（真实接口） */
export async function listSnatchTasks(tenants: TenantOption[]): Promise<SnatchTask[]> {
  const resp = await api.get('/api/v1/snatch-tasks');
  const data = (resp.data ?? []) as BackendSnatchTask[];
  return data.map((b) => toTask(b, tenants));
}

export async function createSnatchTask(body: SnatchTaskCreate): Promise<void> {
  await api.post('/api/v1/snatch-tasks', body);
}

export async function startSnatchTask(id: string): Promise<void> {
  await api.post(`/api/v1/snatch-tasks/${id}/start`);
}

export async function pauseSnatchTask(id: string): Promise<void> {
  await api.post(`/api/v1/snatch-tasks/${id}/pause`);
}

export async function resumeSnatchTask(id: string): Promise<void> {
  await api.post(`/api/v1/snatch-tasks/${id}/resume`);
}

export async function deleteSnatchTask(id: string): Promise<void> {
  await api.delete(`/api/v1/snatch-tasks/${id}`);
}

/** 抢机统计 */
export interface SnatchStats {
  total: number;
  by_status: Record<string, number>;
  total_attempts: number;
  success_rate: number; // 0~1
}

export async function getSnatchStats(): Promise<SnatchStats> {
  const resp = await api.get('/api/v1/snatch-tasks/stats');
  return (resp.data ?? { total: 0, by_status: {}, total_attempts: 0, success_rate: 0 }) as SnatchStats;
}
