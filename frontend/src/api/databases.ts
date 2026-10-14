import { api } from './client';

/** Autonomous Database 管理（全部走后端 /api/v1/databases，实时 OCI 接口） */
export interface AutonomousDb {
  id: string;
  display_name: string;
  db_name: string;
  db_workload: string;
  db_workload_cn: string;
  db_version: string;
  lifecycle_state: string;
  lifecycle_details: string | null;
  is_free_tier: boolean;
  compute_model: string | null;
  compute_count: number | null;
  ocpu_count: number | null;
  data_storage_size_in_tbs: number | null;
  actual_used_data_storage_size_in_tbs: number | null;
  allocated_storage_size_in_tbs: number | null;
  license_model: string | null;
  time_created: string | null;
  service_console_url: string | null;
  connection_strings: { high: string | null } | null;
}

export interface AutonomousDbDetail extends AutonomousDb {
  connection_profiles: Record<string, string>;
  all_connection_strings: Record<string, string>;
}

export interface CreateDbBody {
  tenant_id: number;
  compartment_id: string;
  db_name: string;
  display_name?: string;
  db_workload?: string;
  admin_password: string;
  is_free_tier?: boolean;
  db_version?: string;
}

const asArray = <T>(data: unknown): T[] => (Array.isArray(data) ? (data as T[]) : []);

export async function listDatabases(tenantId: number, compartmentId?: string): Promise<AutonomousDb[]> {
  const resp = await api.get('/api/v1/databases', { params: { tenant_id: tenantId, compartment_id: compartmentId || '' } });
  return asArray<AutonomousDb>(resp.data);
}

export async function getDatabase(tenantId: number, dbId: string): Promise<AutonomousDbDetail> {
  const resp = await api.get(`/api/v1/databases/${dbId}`, { params: { tenant_id: tenantId } });
  return resp.data as AutonomousDbDetail;
}

export async function createDatabase(body: CreateDbBody): Promise<AutonomousDb> {
  const resp = await api.post('/api/v1/databases', body);
  return resp.data as AutonomousDb;
}

export async function deleteDatabase(tenantId: number, dbId: string) {
  const resp = await api.delete(`/api/v1/databases/${dbId}`, { params: { tenant_id: tenantId } });
  return resp.data;
}

export async function startDatabase(tenantId: number, dbId: string) {
  const resp = await api.post(`/api/v1/databases/${dbId}/start`, null, { params: { tenant_id: tenantId } });
  return resp.data;
}

export async function stopDatabase(tenantId: number, dbId: string) {
  const resp = await api.post(`/api/v1/databases/${dbId}/stop`, null, { params: { tenant_id: tenantId } });
  return resp.data;
}

export async function restartDatabase(tenantId: number, dbId: string) {
  const resp = await api.post(`/api/v1/databases/${dbId}/restart`, null, { params: { tenant_id: tenantId } });
  return resp.data;
}

export async function changeDbPassword(tenantId: number, dbId: string, newPassword: string) {
  const resp = await api.post(
    `/api/v1/databases/${dbId}/change-password`,
    { new_password: newPassword },
    { params: { tenant_id: tenantId } },
  );
  return resp.data;
}

/** 下载 Wallet zip，返回可下载的 blob URL */
export async function downloadWallet(tenantId: number, dbId: string, walletPassword: string): Promise<{ url: string; filename: string }> {
  const resp = await api.post(
    `/api/v1/databases/${dbId}/wallet`,
    { wallet_password: walletPassword },
    { params: { tenant_id: tenantId }, responseType: 'blob' },
  );
  const blob = new Blob([resp.data], { type: 'application/zip' });
  const url = URL.createObjectURL(blob);
  return { url, filename: `wallet_${dbId.slice(0, 8)}.zip` };
}
