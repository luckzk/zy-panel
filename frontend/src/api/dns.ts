import { api } from './client';

/** 后端 DNS 记录（与 models.DnsRecord 对齐） */
export interface DnsRecordDto {
  id: number;
  zone_name: string;
  name: string;
  type: 'A' | 'AAAA' | 'CNAME' | 'TXT';
  content: string;
  ttl: number;
  proxied: boolean;
  cf_record_id: string | null;
  note?: string;
}

export interface DnsRecordCreate {
  zone_name: string;
  name: string;
  type: string;
  content: string;
  ttl: number;
  proxied: boolean;
}

export interface PullResult {
  pulled: number;
  created: number;
  updated: number;
}

export async function listDnsRecords(): Promise<DnsRecordDto[]> {
  const resp = await api.get('/api/v1/dns/records');
  return (resp.data ?? []) as DnsRecordDto[];
}

export async function createDnsRecord(body: DnsRecordCreate): Promise<DnsRecordDto> {
  const resp = await api.post('/api/v1/dns/records', body);
  return resp.data as DnsRecordDto;
}

export async function updateDnsRecord(id: number, body: Partial<DnsRecordCreate>): Promise<DnsRecordDto> {
  const resp = await api.put(`/api/v1/dns/records/${id}`, body);
  return resp.data as DnsRecordDto;
}

export async function deleteDnsRecord(id: number): Promise<void> {
  await api.delete(`/api/v1/dns/records/${id}`);
}

/** 手动同步单条到 Cloudflare */
export async function syncDnsRecord(id: number): Promise<DnsRecordDto> {
  const resp = await api.post(`/api/v1/dns/records/${id}/sync`);
  return resp.data as DnsRecordDto;
}

/** 从 Cloudflare 拉取 zone 记录并落库 */
export async function pullDnsRecords(zone_name: string): Promise<PullResult> {
  const resp = await api.post('/api/v1/dns/records/pull', { zone_name });
  return resp.data as PullResult;
}

/** Token 配置状态（不回显 token） */
export async function getCloudflareStatus(): Promise<{ configured: boolean }> {
  const resp = await api.get('/api/v1/dns/settings/cloudflare');
  return resp.data as { configured: boolean };
}

/** 保存 Token（加密存储） */
export async function saveCloudflareToken(api_token: string): Promise<void> {
  await api.put('/api/v1/dns/settings/cloudflare', { api_token });
}
