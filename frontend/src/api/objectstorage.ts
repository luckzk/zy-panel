import { api } from './client';

/** Bucket（后端返回项） */
export interface BucketInfo {
  name: string;
  created: string | null;
}

/** 对象（后端返回项） */
export interface ObjectInfo {
  name: string;
  size: number;
  time_created: string | null;
}

interface ItemsResp<T> {
  items: T[];
  total: number;
}

/** 获取 namespace（真实接口） */
export async function getNamespace(tenant_id: number): Promise<string> {
  const resp = await api.get('/api/v1/object-storage/namespace', { params: { tenant_id } });
  return (resp.data as { namespace: string }).namespace;
}

/** Bucket 列表（真实接口） */
export async function listBuckets(tenant_id: number, compartment_id?: string): Promise<BucketInfo[]> {
  const resp = await api.get('/api/v1/object-storage/buckets', {
    params: { tenant_id, compartment_id: compartment_id || undefined },
  });
  return ((resp.data as ItemsResp<BucketInfo>).items ?? []);
}

/** 创建 Bucket（真实接口） */
export async function createBucket(tenant_id: number, compartment_id: string, name: string): Promise<BucketInfo> {
  const resp = await api.post('/api/v1/object-storage/buckets', { tenant_id, compartment_id, name });
  return resp.data as BucketInfo;
}

/** 删除 Bucket（真实接口，需为空） */
export async function deleteBucket(tenant_id: number, namespace: string, name: string): Promise<void> {
  await api.delete(`/api/v1/object-storage/buckets/${encodeURIComponent(name)}`, {
    params: { tenant_id, namespace },
  });
}

/** 对象列表（真实接口） */
export async function listObjects(
  tenant_id: number,
  namespace: string,
  bucket: string,
  prefix = '',
): Promise<ObjectInfo[]> {
  const resp = await api.get('/api/v1/object-storage/objects', {
    params: { tenant_id, namespace, bucket, prefix: prefix || undefined },
  });
  return ((resp.data as ItemsResp<ObjectInfo>).items ?? []);
}

/** 上传对象（真实接口，FormData） */
export async function uploadObject(
  tenant_id: number,
  namespace: string,
  bucket: string,
  file: File,
  prefix = '',
): Promise<ObjectInfo> {
  const form = new FormData();
  form.append('tenant_id', String(tenant_id));
  form.append('namespace', namespace);
  form.append('bucket', bucket);
  form.append('prefix', prefix);
  form.append('file', file);
  const resp = await api.post('/api/v1/object-storage/objects/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  });
  return resp.data as ObjectInfo;
}

/** 下载对象：返回 blob URL（真实接口） */
export async function downloadObject(
  tenant_id: number,
  namespace: string,
  bucket: string,
  name: string,
): Promise<{ url: string; filename: string }> {
  const resp = await api.get('/api/v1/object-storage/objects/download', {
    params: { tenant_id, namespace, bucket, name },
    responseType: 'blob',
  });
  const url = URL.createObjectURL(resp.data as Blob);
  const filename = name.split('/').pop() || 'download';
  return { url, filename };
}

/** 删除对象（真实接口） */
export async function deleteObject(
  tenant_id: number,
  namespace: string,
  bucket: string,
  name: string,
): Promise<void> {
  await api.delete('/api/v1/object-storage/objects', {
    params: { tenant_id, namespace, bucket, name },
  });
}

/** 格式化字节数 */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

/* ---------- 预签名 URL / 版本控制 / 生命周期（新增） ---------- */

export interface PreauthRequest {
  id: string; name: string; object_name: string | null; access_type: string;
  url: string; time_created: string | null; time_expires: string | null;
}

export interface BucketDetail {
  name: string; namespace: string; versioning: string; public_access_type: string;
  storage_tier: string | null; auto_tiering: string | null;
  approximate_size: number | null; approximate_count: number | null;
  time_created: string | null;
}

export interface LifecycleRule {
  name: string; action: string; is_enabled: boolean; prefix: string;
  time_amount: number; time_unit: string; target: string | null;
}

/** 创建预签名 URL（限时分享链接） */
export async function createPar(
  tenant_id: number, namespace: string, bucket: string,
  object_name: string, expires_hours = 24, access_type = 'ObjectRead',
): Promise<PreauthRequest> {
  const resp = await api.post('/api/v1/object-storage/preauth', {
    tenant_id, namespace, bucket, object_name, expires_hours, access_type,
  });
  return resp.data as PreauthRequest;
}

/** 预签名 URL 列表 */
export async function listPars(tenant_id: number, namespace: string, bucket: string): Promise<PreauthRequest[]> {
  const resp = await api.get('/api/v1/object-storage/preauth', { params: { tenant_id, namespace, bucket } });
  return Array.isArray(resp.data) ? (resp.data as PreauthRequest[]) : [];
}

/** 吊销预签名 URL */
export async function deletePar(tenant_id: number, namespace: string, bucket: string, par_id: string): Promise<void> {
  await api.delete(`/api/v1/object-storage/preauth/${encodeURIComponent(par_id)}`, {
    params: { tenant_id, namespace, bucket },
  });
}

/** Bucket 详情（含版本控制状态） */
export async function getBucketDetail(tenant_id: number, namespace: string, name: string): Promise<BucketDetail> {
  const resp = await api.get(`/api/v1/object-storage/buckets/${encodeURIComponent(name)}/detail`, {
    params: { tenant_id, namespace },
  });
  return resp.data as BucketDetail;
}

/** 开关 Bucket 版本控制 */
export async function setBucketVersioning(tenant_id: number, namespace: string, name: string, enabled: boolean) {
  const resp = await api.post(`/api/v1/object-storage/buckets/${encodeURIComponent(name)}/versioning`, {
    tenant_id, namespace, bucket: name, enabled,
  });
  return resp.data;
}

/** 查询生命周期规则 */
export async function getLifecycle(tenant_id: number, namespace: string, name: string): Promise<LifecycleRule[]> {
  const resp = await api.get(`/api/v1/object-storage/buckets/${encodeURIComponent(name)}/lifecycle`, {
    params: { tenant_id, namespace },
  });
  return Array.isArray(resp.data) ? (resp.data as LifecycleRule[]) : [];
}

/** 覆盖设置生命周期规则 */
export async function putLifecycle(
  tenant_id: number, namespace: string, name: string,
  rules: { name?: string; action: string; prefix: string; days: number }[],
) {
  const resp = await api.put(`/api/v1/object-storage/buckets/${encodeURIComponent(name)}/lifecycle`, {
    tenant_id, namespace, bucket: name, rules,
  });
  return resp.data;
}
