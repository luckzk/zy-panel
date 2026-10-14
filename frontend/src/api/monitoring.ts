import { api } from './client';

export interface TrafficPoint {
  time: string;
  inbound_mbps: number;
  outbound_mbps: number;
}

export interface TrafficData {
  tenant_id: number;
  instance_id: string;
  vnic_id: string;
  points: TrafficPoint[];
}

export interface QuotaItem {
  name: string;
  value: number;
}

/** 实例流量时序（真实 OCI 指标）；instanceId 不传则后端取第一个运行中实例 */
export async function getTraffic(
  tenantId: number,
  instanceId?: string,
  hours: number = 24,
  resolution: '1m' | '5m' | '1h' = '1h',
): Promise<TrafficData> {
  const resp = await api.get('/api/v1/monitoring/traffic', {
    params: { tenant_id: tenantId, instance_id: instanceId || undefined, hours, resolution },
  });
  return resp.data as TrafficData;
}

/** 实例峰值带宽（近 N 小时出向/入向 Mbps 实测峰值） */
export interface PeakBandwidth {
  instance_id: string;
  vnic_id: string;
  hours: number;
  peak_egress_mbps: number;
  peak_ingress_mbps: number;
}

export async function getPeakBandwidth(
  tenantId: number,
  instanceId: string,
  hours: number = 24,
): Promise<PeakBandwidth> {
  const resp = await api.get('/api/v1/monitoring/bandwidth', {
    params: { tenant_id: tenantId, instance_id: instanceId, hours },
  });
  return resp.data as PeakBandwidth;
}

/** compute 服务配额 */
export async function getQuotas(tenantId: number): Promise<QuotaItem[]> {
  const resp = await api.get('/api/v1/monitoring/quotas', { params: { tenant_id: tenantId } });
  const data = resp.data as { quotas?: QuotaItem[] };
  return data.quotas ?? [];
}
