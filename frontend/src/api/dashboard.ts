import { api } from './client';

export interface NameValue {
  name: string;
  value: number;
}

export interface DashboardOverview {
  tenants: number;
  instances: {
    total: number;
    running: number;
    stopped: number;
    by_region: NameValue[];
    by_shape: NameValue[];
  };
  snatch: {
    running: number;
    success: number;
    failed: number;
    total: number;
  };
  ip_changes_today: number;
  dns_records: number;
  errors: { tenant_id: number; tenant_name: string; error: string }[];
}

/** 总览聚合（真实数据）；失败时抛错，由调用方处理 */
export async function getOverview(tenantIds?: number[]): Promise<DashboardOverview> {
  const params = tenantIds && tenantIds.length ? { tenant_ids: tenantIds.join(',') } : {};
  const resp = await api.get('/api/v1/dashboard/overview', { params });
  return resp.data as DashboardOverview;
}
