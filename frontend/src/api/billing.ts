import { api } from './client';

export interface DailyCost {
  date: string;
  amount: number;
}

export interface ServiceCost {
  name: string;
  amount: number;
}

export interface BillingSummary {
  total: number;
  currency: string;
  by_service: ServiceCost[];
  daily: DailyCost[];
  days: number;
}

export interface BillingDetail {
  time: string;
  service: string;
  resource_id: string;
  resource_name: string;
  amount: number;
  quantity: number;
  currency: string;
}

/** 费用汇总（真实 OCI 用量） */
export async function getBillingSummary(tenantId: number, days = 30): Promise<BillingSummary> {
  const resp = await api.get('/api/v1/billing/summary', { params: { tenant_id: tenantId, days } });
  return resp.data as BillingSummary;
}

/** 费用明细（真实 OCI 用量） */
export async function getBillingDetails(tenantId: number, days = 30): Promise<BillingDetail[]> {
  const resp = await api.get('/api/v1/billing/details', { params: { tenant_id: tenantId, days } });
  const data = resp.data as { items?: BillingDetail[] };
  return data.items ?? [];
}
