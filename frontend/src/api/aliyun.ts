import { api } from './client';

/** 云盘（归一化卷） */
export interface AliDisk {
  id: string;
  name: string;
  region: string;
  zone: string;
  size_gb: number;
  status: string;
  volume_type: string;
  attached_instance_id: string | null;
  created_at: string | null;
}

export interface AliSnapshot {
  id: string;
  name: string;
  disk_id: string;
  disk_name: string;
  size_gb: number;
  status: string;
  progress: string;
  created_at: string;
  usage: string;
}

export interface AliEip {
  id: string;
  ip: string;
  status: string;
  instance_id: string;
  instance_type: string;
  bandwidth: string;
  internet_charge_type: string;
  created_at: string;
}

export interface MetricChart {
  metric: string;
  title: string;
  points: { time: string; value: number }[];
  error?: string;
}

export async function listAliDisks(tenantId: number): Promise<AliDisk[]> {
  const resp = await api.get('/api/v1/aliyun/disks', { params: { tenant_id: tenantId } });
  return (resp.data as AliDisk[]) ?? [];
}

export async function resizeAliDisk(tenantId: number, diskId: string, newSizeGb: number): Promise<void> {
  await api.post(`/api/v1/aliyun/disks/${encodeURIComponent(diskId)}/resize`, {
    tenant_id: tenantId, new_size_gb: newSizeGb,
  });
}

export async function listAliSnapshots(tenantId: number, diskId?: string): Promise<AliSnapshot[]> {
  const resp = await api.get('/api/v1/aliyun/snapshots', {
    params: { tenant_id: tenantId, ...(diskId ? { disk_id: diskId } : {}) },
  });
  return (resp.data as AliSnapshot[]) ?? [];
}

export async function createAliSnapshot(tenantId: number, diskId: string, name: string): Promise<void> {
  await api.post('/api/v1/aliyun/snapshots', { tenant_id: tenantId, disk_id: diskId, name });
}

export async function deleteAliSnapshot(tenantId: number, snapshotId: string): Promise<void> {
  await api.delete(`/api/v1/aliyun/snapshots/${encodeURIComponent(snapshotId)}`, {
    params: { tenant_id: tenantId },
  });
}

export async function listAliEips(tenantId: number): Promise<AliEip[]> {
  const resp = await api.get('/api/v1/aliyun/eips', { params: { tenant_id: tenantId } });
  return (resp.data as AliEip[]) ?? [];
}

export async function allocateAliEip(tenantId: number, bandwidth: number): Promise<{ allocation_id: string; ip: string }> {
  const resp = await api.post('/api/v1/aliyun/eips', { tenant_id: tenantId, bandwidth });
  return resp.data as { allocation_id: string; ip: string };
}

export async function bindAliEip(tenantId: number, allocationId: string, instanceId: string): Promise<void> {
  await api.post('/api/v1/aliyun/eips/bind', {
    tenant_id: tenantId, allocation_id: allocationId, instance_id: instanceId,
  });
}

export async function unbindAliEip(tenantId: number, allocationId: string, instanceId: string): Promise<void> {
  await api.post('/api/v1/aliyun/eips/unbind', {
    tenant_id: tenantId, allocation_id: allocationId, instance_id: instanceId,
  });
}

export async function releaseAliEip(tenantId: number, allocationId: string): Promise<void> {
  await api.delete(`/api/v1/aliyun/eips/${encodeURIComponent(allocationId)}`, {
    params: { tenant_id: tenantId },
  });
}

export async function getAliInstanceMetrics(tenantId: number, instanceId: string, hours = 6): Promise<MetricChart[]> {
  const resp = await api.get(`/api/v1/aliyun/instances/${encodeURIComponent(instanceId)}/metrics`, {
    params: { tenant_id: tenantId, hours },
  });
  const data = resp.data as { charts?: MetricChart[] };
  return data.charts ?? [];
}

/** 镜像 */
export interface AliImage {
  id: string;
  name: string;
  os_name: string;
  os_type: string;
  architecture: string;
  size_gb: number;
  status: string;
  created_at: string;
  description: string;
}

export async function listAliImages(tenantId: number): Promise<AliImage[]> {
  const resp = await api.get('/api/v1/aliyun/images', { params: { tenant_id: tenantId } });
  return (resp.data as AliImage[]) ?? [];
}

export async function listAliPublicImages(tenantId: number, osType = 'linux'): Promise<AliImage[]> {
  const resp = await api.get('/api/v1/aliyun/images/public', { params: { tenant_id: tenantId, os_type: osType } });
  return (resp.data as AliImage[]) ?? [];
}

export async function createAliImage(tenantId: number, body: {
  instance_id?: string; snapshot_id?: string; name: string; description?: string;
}): Promise<void> {
  await api.post('/api/v1/aliyun/images', { tenant_id: tenantId, ...body });
}

export async function deleteAliImage(tenantId: number, imageId: string): Promise<void> {
  await api.delete(`/api/v1/aliyun/images/${encodeURIComponent(imageId)}`, { params: { tenant_id: tenantId } });
}

/** 费用 */
export interface AliBilling {
  balance: { available_amount: string; credit_amount: string; currency: string };
  bill: { billing_cycle: string; total: number; products: { product: string; product_code: string; amount: number; currency: string }[]; error?: string };
}

export async function getAliBilling(tenantId: number): Promise<AliBilling> {
  const resp = await api.get('/api/v1/aliyun/billing/summary', { params: { tenant_id: tenantId } });
  return resp.data as AliBilling;
}

/** 实例规格 / 交换机 */
export interface AliInstanceType { id: string; cpu: number; memory_gb: number; family: string }
export interface AliVSwitch { id: string; name: string; zone_id: string; cidr: string; vpc_id: string }

export async function listAliInstanceTypes(tenantId: number, zoneId = ''): Promise<AliInstanceType[]> {
  const resp = await api.get('/api/v1/aliyun/instance-types', { params: { tenant_id: tenantId, zone_id: zoneId } });
  return (resp.data as AliInstanceType[]) ?? [];
}

export async function listAliVSwitches(tenantId: number, zoneId = ''): Promise<AliVSwitch[]> {
  const resp = await api.get('/api/v1/aliyun/vswitches', { params: { tenant_id: tenantId, zone_id: zoneId } });
  return (resp.data as AliVSwitch[]) ?? [];
}

/** 抢占式任务 */
export interface AliSpotTask {
  id: number; tenant_id: number; name: string;
  region_id: string; zone_id: string; instance_type: string; image_id: string;
  vswitch_id: string; security_group_id: string;
  spot_strategy: string; spot_price_limit: string | null;
  system_disk_category: string; system_disk_size: number;
  bandwidth_out: number; instance_name: string;
  status: string; interval_sec: number; max_attempts: number;
  attempts: number; last_error: string | null;
  recent_logs: { time: string; ok: boolean; error: string; instance_id: string }[];
  last_attempt_at: string | null; next_attempt_at: string | null;
  created_instance_id: string | null;
}

export interface AliSpotTaskInput {
  tenant_id: number; name: string; region_id: string; zone_id?: string;
  instance_type: string; image_id: string; vswitch_id: string; security_group_id: string;
  spot_strategy?: string; spot_price_limit?: string;
  system_disk_category?: string; system_disk_size?: number;
  bandwidth_out?: number; instance_name?: string;
  interval_sec?: number; max_attempts?: number;
}

export async function listAliSpotTasks(tenantId: number): Promise<AliSpotTask[]> {
  const resp = await api.get('/api/v1/aliyun/spot-tasks', { params: { tenant_id: tenantId } });
  return (resp.data as AliSpotTask[]) ?? [];
}

export async function createAliSpotTask(body: AliSpotTaskInput): Promise<AliSpotTask> {
  const resp = await api.post('/api/v1/aliyun/spot-tasks', body);
  return resp.data as AliSpotTask;
}

export async function startAliSpotTask(id: number): Promise<void> {
  await api.post(`/api/v1/aliyun/spot-tasks/${id}/start`);
}

export async function pauseAliSpotTask(id: number): Promise<void> {
  await api.post(`/api/v1/aliyun/spot-tasks/${id}/pause`);
}

export async function deleteAliSpotTask(id: number): Promise<void> {
  await api.delete(`/api/v1/aliyun/spot-tasks/${id}`);
}
