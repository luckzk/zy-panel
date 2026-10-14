import { api } from './client';

export interface FreeTierItem {
  key: string;
  name: string;
  limit: number | null; // null 表示仅统计、无明确免费上限
  unit: string;
  used: number | null;
  unknown: boolean;
  detail?: unknown;
}

export interface FreeTierSummary {
  tenant_id: number;
  items: FreeTierItem[];
  generated_at: string;
  cached?: boolean;
}

/** 免费额度使用情况汇总（后端 10 分钟缓存） */
export async function getFreeTierSummary(tenantId: number, refresh = false): Promise<FreeTierSummary> {
  const resp = await api.get('/api/v1/free-tier/summary', {
    params: { tenant_id: tenantId, refresh },
  });
  return resp.data as FreeTierSummary;
}
