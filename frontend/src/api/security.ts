import { api } from './client';

/** VCN（后端 GET /api/v1/security/vcns 返回项） */
export interface VcnInfo {
  id: string;
  name: string;
  cidr: string;
}

/** 安全规则（后端 GET /api/v1/security/rules 返回项） */
export interface SecurityRuleInfo {
  id: string;
  securityListId: string;
  securityListName: string;
  direction: 'ingress' | 'egress';
  protocol: string;
  ports: string;
  source: string;
  description: string;
}

interface BackendVcn {
  id: string;
  display_name: string;
  cidr_block: string;
}

interface BackendRule {
  id: string;
  security_list_id: string;
  security_list_name: string;
  direction: string;
  protocol: string;
  port_range: string;
  source: string;
  description: string;
}

/** VCN 列表（真实接口） */
export async function listVcns(tenant_id: number, compartment_id?: string): Promise<VcnInfo[]> {
  const resp = await api.get('/api/v1/security/vcns', { params: { tenant_id, compartment_id: compartment_id || undefined } });
  const items = (resp.data?.items ?? []) as BackendVcn[];
  return items.map((v) => ({ id: v.id, name: v.display_name || '-', cidr: v.cidr_block || '-' }));
}

/** 安全规则列表（真实接口） */
export async function listSecurityRules(
  tenant_id: number,
  vcn_id: string,
  compartment_id?: string,
): Promise<SecurityRuleInfo[]> {
  const resp = await api.get('/api/v1/security/rules', {
    params: { tenant_id, vcn_id, compartment_id: compartment_id || undefined },
  });
  const items = (resp.data?.items ?? []) as BackendRule[];
  return items.map((r) => ({
    id: r.id,
    securityListId: r.security_list_id,
    securityListName: r.security_list_name,
    direction: r.direction === 'egress' ? 'egress' : 'ingress',
    protocol: r.protocol,
    ports: r.port_range,
    source: r.source,
    description: r.description,
  }));
}

/** 新增安全规则（真实接口） */
export async function addSecurityRule(
  tenant_id: number,
  body: { security_list_id: string; direction: string; protocol: string; port_range: string; cidr: string; description?: string },
): Promise<void> {
  await api.post('/api/v1/security/rules', body, { params: { tenant_id } });
}

/** 删除安全规则（真实接口） */
export async function deleteSecurityRule(tenant_id: number, rule_id: string): Promise<void> {
  await api.delete(`/api/v1/security/rules/${encodeURIComponent(rule_id)}`, { params: { tenant_id } });
}

/** 一键放行所有端口（真实接口，危险操作：追加 0.0.0.0/0 与 ::/0 全协议入站规则） */
export async function openAllPorts(
  tenant_id: number,
  security_list_id: string,
): Promise<{ security_list_id: string; added: string[]; already_open: string[] }> {
  const resp = await api.post('/api/v1/security/open-all-ports', null, {
    params: { tenant_id, security_list_id },
  });
  return resp.data as { security_list_id: string; added: string[]; already_open: string[] };
}
