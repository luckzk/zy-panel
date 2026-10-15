import { api } from './client';

/** 租户下拉选项（后端 GET /api/v1/tenants 返回数组） */
export interface TenantOption {
  id: number;
  name: string;
  region: string;
  provider?: string;
}

/** 租户列表（下拉用） */
export async function listTenants(): Promise<TenantOption[]> {
  const resp = await api.get('/api/v1/tenants');
  const data = resp.data;
  return Array.isArray(data) ? data : [];
}

/** 租户详情（后端返回，永不含私钥/密钥） */
export interface TenantDetail {
  id: number;
  name: string;
  provider: string; // oci / aliyun
  tenancy_ocid: string;
  user_ocid: string;
  fingerprint: string;
  region: string;
  proxy: string | null;
  account_type: string; // free / paid / ''（手动标记，OCI 无 API 可查）
  test_status: string; // success / failed / ''（连通性测试持久化状态）
  last_tested_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  access_key_id_masked?: string; // 阿里云脱敏 AK ID（后端返回）
}

export interface TenantCreateInput {
  name: string;
  provider?: string; // oci / aliyun，默认 oci
  // OCI 字段
  tenancy_ocid: string;
  user_ocid: string;
  fingerprint: string;
  region: string;
  private_key: string;
  // 阿里云字段
  access_key_id?: string;
  access_key_secret?: string;
  aliyun_region?: string;
  proxy?: string | null;
  account_type?: string;
}

/** 已注册云厂商（后端 GET /api/v1/tenants/providers） */
export interface ProviderInfo {
  id: string;
  name: string;
  capabilities: string[];
}

export async function listProviders(): Promise<ProviderInfo[]> {
  const resp = await api.get('/api/v1/tenants/providers');
  return resp.data as ProviderInfo[];
}

/** 地域列表（按云厂商分发，实时） */
export interface CloudRegion {
  id: string;
  name: string;
  provider: string;
}

export async function listTenantRegions(tenantId: number): Promise<CloudRegion[]> {
  const resp = await api.get(`/api/v1/tenants/${tenantId}/regions`);
  return resp.data as CloudRegion[];
}

export interface TenantUpdateInput {
  name?: string;
  tenancy_ocid?: string;
  user_ocid?: string;
  fingerprint?: string;
  region?: string;
  /** 传入则更新加密私钥；不传/空字符串则保持不变 */
  private_key?: string;
  /** 阿里云：传入则更新 */
  access_key_id?: string;
  access_key_secret?: string;
  aliyun_region?: string;
  proxy?: string | null;
  account_type?: string;
}

export interface TestConnectionResult {
  reachable: boolean;
  region: string;
  availability_domains: string[];
}

/** 租户列表（完整字段） */
export async function getTenantList(): Promise<TenantDetail[]> {
  const resp = await api.get('/api/v1/tenants');
  const data = resp.data;
  return Array.isArray(data) ? (data as TenantDetail[]) : [];
}

/** 新建租户 */
export async function createTenant(body: TenantCreateInput): Promise<void> {
  await api.post('/api/v1/tenants', body);
}

export interface BatchTenantResult {
  total: number;
  success: number;
  failed: number;
  results: { ok: boolean; name: string; id?: number; error?: string }[];
}

/** 批量新增租户 */
export async function batchCreateTenants(body: TenantCreateInput[]): Promise<BatchTenantResult> {
  const resp = await api.post('/api/v1/tenants/batch', body);
  return resp.data as BatchTenantResult;
}

/** 更新租户 */
export async function updateTenant(id: number, body: TenantUpdateInput): Promise<void> {
  await api.put(`/api/v1/tenants/${id}`, body);
}

/** 删除租户 */
export async function deleteTenant(id: number): Promise<void> {
  await api.delete(`/api/v1/tenants/${id}`);
}

/** 连通性测试（真实 OCI 校验） */
export async function testTenantConnection(id: number): Promise<TestConnectionResult> {
  const resp = await api.post(`/api/v1/tenants/${id}/test`);
  return resp.data as TestConnectionResult;
}

/** 账号类型启发式检测（结果自动写入租户，仅供参考） */
export interface DetectAccountTypeResult {
  detected: 'free' | 'paid' | 'unknown';
  reasons: string[];
}

export async function detectAccountType(id: number): Promise<DetectAccountTypeResult> {
  const resp = await api.post(`/api/v1/tenants/${id}/detect-account-type`);
  return resp.data as DetectAccountTypeResult;
}
