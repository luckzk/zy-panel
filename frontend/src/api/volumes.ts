import { api } from './client';

/** 引导卷（后端 GET /api/v1/volumes 返回项） */
export interface VolumeInfo {
  id: string;
  name: string;
  sizeGb: number;
  status: string;
  ad: string | null;
  instanceId: string | null;
  instanceName: string;
  createdAt: string | null;
}

interface BackendVolume {
  id: string;
  display_name: string;
  size_in_gbs: number;
  lifecycle_state: string;
  availability_domain: string | null;
  instance_id: string | null;
  instance_name: string;
  time_created: string | null;
}

function toVolume(b: BackendVolume): VolumeInfo {
  return {
    id: b.id,
    name: b.display_name || '-',
    sizeGb: b.size_in_gbs,
    status: b.lifecycle_state,
    ad: b.availability_domain,
    instanceId: b.instance_id,
    instanceName: b.instance_name || '',
    createdAt: b.time_created ? new Date(b.time_created).toLocaleString('zh-CN', { hour12: false }) : null,
  };
}

/** 引导卷列表（真实接口）。compartment_id 为空时后端默认用租户根 compartment。 */
export async function listVolumes(tenant_id: number, compartment_id?: string): Promise<VolumeInfo[]> {
  const resp = await api.get('/api/v1/volumes', { params: { tenant_id, compartment_id: compartment_id || undefined } });
  const items = (resp.data?.items ?? []) as BackendVolume[];
  return items.map(toVolume);
}

/** 数据卷列表（真实接口） */
export async function listBlockVolumes(tenant_id: number, compartment_id?: string): Promise<VolumeInfo[]> {
  const resp = await api.get('/api/v1/volumes/block', { params: { tenant_id, compartment_id: compartment_id || undefined } });
  const items = (resp.data?.items ?? []) as BackendVolume[];
  return items.map(toVolume);
}

/** 引导卷扩容（真实接口） */
export async function resizeVolume(tenant_id: number, volume_id: string, size_in_gbs: number, kind: 'boot' | 'block' = 'boot'): Promise<VolumeInfo> {
  const path = kind === 'boot' ? `/api/v1/volumes/${volume_id}/resize` : `/api/v1/volumes/block/${volume_id}/resize`;
  const resp = await api.post(path, { size_in_gbs }, { params: { tenant_id } });
  return toVolume(resp.data as BackendVolume);
}

/** 救援结果 */
export interface RescueResult {
  volume_id: string;
  rescue_instance_id: string;
  attachment_id: string;
  lifecycle_state: string | null;
}

/** 救援：把引导卷挂载到救援实例（真实接口） */
export async function rescueVolume(
  tenant_id: number,
  volume_id: string,
  rescue_instance_id: string,
): Promise<RescueResult> {
  const resp = await api.post(`/api/v1/volumes/${volume_id}/rescue`, { tenant_id, rescue_instance_id });
  return resp.data as RescueResult;
}

/** 解除救援：卸载引导卷的全部挂载（真实接口） */
export async function unrescueVolume(
  tenant_id: number,
  volume_id: string,
): Promise<{ volume_id: string; detached_attachments: string[]; count: number }> {
  const resp = await api.post(`/api/v1/volumes/${volume_id}/unrescue`, { tenant_id });
  return resp.data as { volume_id: string; detached_attachments: string[]; count: number };
}
