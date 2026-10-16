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

export interface RamUser {
  user_name: string;
  display_name: string;
  mobile: string;
  email: string;
  comments: string;
  create_date: string;
}

export interface RamAccessKey {
  access_key_id: string;
  status: string;
  create_date: string;
}

/** RAM 用户列表 */
export async function listRamUsers(tenantId: number): Promise<RamUser[]> {
  const resp = await api.get('/api/v1/aliyun/ram/users', { params: { tenant_id: tenantId } });
  return resp.data as RamUser[];
}

/** 创建 RAM 用户 */
export async function createRamUser(tenantId: number, body: {
  user_name: string; display_name?: string; mobile_phone?: string; email?: string; comments?: string;
}): Promise<{ user_name: string }> {
  const resp = await api.post('/api/v1/aliyun/ram/users', { tenant_id: tenantId, ...body });
  return resp.data as { user_name: string };
}

/** 删除 RAM 用户（含其 AccessKey） */
export async function deleteRamUser(tenantId: number, userName: string): Promise<void> {
  await api.delete(`/api/v1/aliyun/ram/users/${encodeURIComponent(userName)}`, { params: { tenant_id: tenantId } });
}

/** RAM 用户 AccessKey 列表 */
export async function listRamAccessKeys(tenantId: number, userName: string): Promise<RamAccessKey[]> {
  const resp = await api.get(`/api/v1/aliyun/ram/users/${encodeURIComponent(userName)}/keys`, { params: { tenant_id: tenantId } });
  return resp.data as RamAccessKey[];
}

/** 创建 AccessKey（Secret 仅返回一次） */
export async function createRamAccessKey(tenantId: number, userName: string): Promise<{ access_key_id: string; access_key_secret: string }> {
  const resp = await api.post(`/api/v1/aliyun/ram/users/${encodeURIComponent(userName)}/keys`, { tenant_id: tenantId });
  return resp.data as { access_key_id: string; access_key_secret: string };
}

/** 删除 AccessKey */
export async function deleteRamAccessKey(tenantId: number, userName: string, keyId: string): Promise<void> {
  await api.delete(`/api/v1/aliyun/ram/users/${encodeURIComponent(userName)}/keys/${encodeURIComponent(keyId)}`, { params: { tenant_id: tenantId } });
}

export interface AliSecurityGroup {
  id: string;
  name: string;
  description: string;
  region: string;
}

export interface AliSgRule {
  direction: string; // ingress / egress
  protocol: string;
  port_range: string;
  cidr: string;
  policy: string;
  priority: string | number;
  description: string;
}

/** 安全组列表 */
export async function listAliSecurityGroups(tenantId: number, regionId?: string): Promise<AliSecurityGroup[]> {
  const resp = await api.get('/api/v1/aliyun/security-groups', { params: { tenant_id: tenantId, region_id: regionId || undefined } });
  return resp.data as AliSecurityGroup[];
}

/** 安全组规则列表 */
export async function listAliSgRules(tenantId: number, sgId: string, regionId?: string): Promise<AliSgRule[]> {
  const resp = await api.get(`/api/v1/aliyun/security-groups/${encodeURIComponent(sgId)}/rules`, {
    params: { tenant_id: tenantId, region_id: regionId || undefined },
  });
  return resp.data as AliSgRule[];
}

/** 添加安全组规则 */
export async function addAliSgRule(
  tenantId: number,
  sgId: string,
  body: { direction: string; protocol: string; port_range: string; cidr: string; description?: string },
  regionId?: string,
): Promise<void> {
  await api.post(`/api/v1/aliyun/security-groups/${encodeURIComponent(sgId)}/rules`, {
    tenant_id: tenantId,
    region_id: regionId || undefined,
    ...body,
  });
}

/** 删除安全组规则 */
export async function deleteAliSgRule(
  tenantId: number,
  sgId: string,
  rule: { direction: string; protocol: string; port_range: string; cidr: string },
  regionId?: string,
): Promise<void> {
  await api.delete(`/api/v1/aliyun/security-groups/${encodeURIComponent(sgId)}/rules`, {
    params: { tenant_id: tenantId, region_id: regionId || undefined, ...rule },
  });
}

/** 创建安全组 */
export async function createAliSecurityGroup(
  tenantId: number,
  body: { name: string; description?: string; vpc_id?: string },
  regionId?: string,
): Promise<{ security_group_id: string }> {
  const resp = await api.post('/api/v1/aliyun/security-groups', {
    tenant_id: tenantId,
    region_id: regionId || undefined,
    ...body,
  });
  return resp.data as { security_group_id: string };
}

/** 删除安全组 */
export async function deleteAliSecurityGroup(tenantId: number, sgId: string, regionId?: string): Promise<void> {
  await api.delete(`/api/v1/aliyun/security-groups/${encodeURIComponent(sgId)}`, {
    params: { tenant_id: tenantId, region_id: regionId || undefined },
  });
}

/* ---------------- VPC / 交换机 ---------------- */
export interface AliVpc {
  id: string;
  name: string;
  cidr: string;
  description: string;
  status: string;
}

export interface AliVSwitch {
  id: string;
  name: string;
  cidr: string;
  zone_id: string;
  vpc_id: string;
  status: string;
}

export async function listAliVpcs(tenantId: number, regionId?: string): Promise<AliVpc[]> {
  const resp = await api.get('/api/v1/aliyun/vpcs', { params: { tenant_id: tenantId, region_id: regionId || undefined } });
  return resp.data as AliVpc[];
}

export async function createAliVpc(tenantId: number, body: { name: string; cidr: string; description?: string }, regionId?: string): Promise<{ vpc_id: string }> {
  const resp = await api.post('/api/v1/aliyun/vpcs', { tenant_id: tenantId, region_id: regionId || undefined, ...body });
  return resp.data as { vpc_id: string };
}

export async function deleteAliVpc(tenantId: number, vpcId: string, regionId?: string): Promise<void> {
  await api.delete(`/api/v1/aliyun/vpcs/${encodeURIComponent(vpcId)}`, { params: { tenant_id: tenantId, region_id: regionId || undefined } });
}

export async function listAliVSwitchesFull(tenantId: number, vpcId?: string, regionId?: string): Promise<AliVSwitch[]> {
  const resp = await api.get('/api/v1/aliyun/vswitches', {
    params: { tenant_id: tenantId, vpc_id: vpcId || undefined, region_id: regionId || undefined },
  });
  return resp.data as AliVSwitch[];
}

export async function createAliVSwitch(
  tenantId: number,
  body: { vpc_id: string; zone_id: string; cidr: string; name?: string; description?: string },
  regionId?: string,
): Promise<{ vswitch_id: string }> {
  const resp = await api.post('/api/v1/aliyun/vswitches', { tenant_id: tenantId, region_id: regionId || undefined, ...body });
  return resp.data as { vswitch_id: string };
}

export async function deleteAliVSwitch(tenantId: number, vswitchId: string, regionId?: string): Promise<void> {
  await api.delete(`/api/v1/aliyun/vswitches/${encodeURIComponent(vswitchId)}`, {
    params: { tenant_id: tenantId, region_id: regionId || undefined },
  });
}

/* ---------------- OSS 对象存储 ---------------- */
export interface AliOssBucket {
  name: string;
  location: string;
  creation_date: string;
  storage_class: string;
}

export interface AliOssObject {
  key: string;
  size: number;
  last_modified: string;
  etag: string;
  type: string; // file / dir
}

export async function listAliOssBuckets(tenantId: number): Promise<AliOssBucket[]> {
  const resp = await api.get('/api/v1/aliyun/oss/buckets', { params: { tenant_id: tenantId } });
  return resp.data as AliOssBucket[];
}

export async function createAliOssBucket(tenantId: number, bucketName: string, regionId?: string): Promise<void> {
  await api.post('/api/v1/aliyun/oss/buckets', { tenant_id: tenantId, bucket_name: bucketName, region_id: regionId || undefined });
}

export async function deleteAliOssBucket(tenantId: number, bucketName: string): Promise<void> {
  await api.delete(`/api/v1/aliyun/oss/buckets/${encodeURIComponent(bucketName)}`, { params: { tenant_id: tenantId } });
}

export async function listAliOssObjects(tenantId: number, bucketName: string, prefix = ''): Promise<AliOssObject[]> {
  const resp = await api.get(`/api/v1/aliyun/oss/buckets/${encodeURIComponent(bucketName)}/objects`, {
    params: { tenant_id: tenantId, prefix },
  });
  return resp.data as AliOssObject[];
}

export async function deleteAliOssObject(tenantId: number, bucketName: string, key: string): Promise<void> {
  await api.delete(`/api/v1/aliyun/oss/buckets/${encodeURIComponent(bucketName)}/objects`, {
    params: { tenant_id: tenantId, key },
  });
}

export async function getAliOssDownloadUrl(tenantId: number, bucketName: string, key: string): Promise<string> {
  const resp = await api.get(`/api/v1/aliyun/oss/buckets/${encodeURIComponent(bucketName)}/download-url`, {
    params: { tenant_id: tenantId, key },
  });
  return (resp.data as { url: string }).url;
}

export async function uploadAliOssObject(tenantId: number, bucketName: string, file: File, prefix = ''): Promise<void> {
  const form = new FormData();
  form.append('file', file);
  await api.post(`/api/v1/aliyun/oss/buckets/${encodeURIComponent(bucketName)}/upload`, form, {
    params: { tenant_id: tenantId, prefix },
    headers: { 'Content-Type': 'multipart/form-data' },
  });
}

/* ---------------- RDS 数据库 ---------------- */
export interface AliRdsInstance {
  id: string;
  name: string;
  engine: string;
  engine_version: string;
  status: string;
  instance_class: string;
  memory: number;
  storage: number;
  connection: string;
  port: number;
  region: string;
  creation_time: string;
  pay_type: string;
  [key: string]: unknown;
}

export interface AliRdsDatabase {
  name: string;
  status: string;
  description: string;
}

export interface AliRdsAccount {
  name: string;
  status: string;
  type: string;
}

export async function listAliRdsInstances(tenantId: number, regionId?: string): Promise<AliRdsInstance[]> {
  const resp = await api.get('/api/v1/aliyun/rds/instances', { params: { tenant_id: tenantId, region_id: regionId || undefined } });
  return resp.data as AliRdsInstance[];
}

export async function getAliRdsInstance(tenantId: number, dbId: string, regionId?: string): Promise<AliRdsInstance> {
  const resp = await api.get(`/api/v1/aliyun/rds/instances/${encodeURIComponent(dbId)}`, {
    params: { tenant_id: tenantId, region_id: regionId || undefined },
  });
  return resp.data as AliRdsInstance;
}

export async function listAliRdsDatabases(tenantId: number, dbId: string, regionId?: string): Promise<AliRdsDatabase[]> {
  const resp = await api.get(`/api/v1/aliyun/rds/instances/${encodeURIComponent(dbId)}/databases`, {
    params: { tenant_id: tenantId, region_id: regionId || undefined },
  });
  return resp.data as AliRdsDatabase[];
}

export async function listAliRdsAccounts(tenantId: number, dbId: string, regionId?: string): Promise<AliRdsAccount[]> {
  const resp = await api.get(`/api/v1/aliyun/rds/instances/${encodeURIComponent(dbId)}/accounts`, {
    params: { tenant_id: tenantId, region_id: regionId || undefined },
  });
  return resp.data as AliRdsAccount[];
}

/* ---------------- 流量监控 ---------------- */
export interface AliInstanceMetrics {
  instance_id: string;
  instance_name: string;
  metrics: { metric: string; title: string; points: { time: string; value: number }[] }[];
}

export interface AliMonitoringOverview {
  instances: AliInstanceMetrics[];
  summary: { total_in_bps: number; total_out_bps: number; time: string };
}

export async function getAliMonitoringOverview(tenantId: number, regionId?: string, hours = 6): Promise<AliMonitoringOverview> {
  const resp = await api.get('/api/v1/aliyun/monitoring/overview', {
    params: { tenant_id: tenantId, region_id: regionId || undefined, hours },
  });
  return resp.data as AliMonitoringOverview;
}
