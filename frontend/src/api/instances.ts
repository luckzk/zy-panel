import { api } from './client';
import type { Instance, InstanceStatus } from '../types';

/** 后端实例列表查询参数 */
export interface InstanceQuery {
  tenant_id: number;
  state?: string;
  search?: string;
  page?: number;
  page_size?: number;
}

/** 后端返回的实例（snake_case） */
interface BackendInstance {
  id: string;
  display_name: string | null;
  lifecycle_state: string;
  shape: string | null;
  ocpus: number | null;
  memory_in_gbs: number | null;
  region: string;
  availability_domain: string | null;
  compartment_name: string;
  public_ip: string | null;
  private_ip: string | null;
  time_created: string | null;
}

const KNOWN_STATUS: InstanceStatus[] = ['RUNNING', 'STOPPED', 'STARTING', 'STOPPING', 'TERMINATED'];

/** 后端生命周期状态 -> 前端展示状态 */
function toStatus(raw: string): InstanceStatus {
  if ((KNOWN_STATUS as string[]).includes(raw)) return raw as InstanceStatus;
  if (raw === 'TERMINATING') return 'STOPPING';
  if (raw === 'PROVISIONING') return 'STARTING';
  return 'STOPPED';
}

/** snake_case -> 前端 Instance 类型（兼容 OCI 原生与多云归一化两种形状） */
function toInstance(b: BackendInstance, tenantName: string): Instance {
  const provider = (b as unknown as { provider?: string }).provider || 'oci';
  if (provider !== 'oci') {
    // 多云归一化 DTO：{id,name,provider,region,zone,status,spec,cpu,memory_gb,...}
    const n = b as unknown as Record<string, unknown>;
    const str = (v: unknown) => (typeof v === 'string' ? v : '');
    const num = (v: unknown) => (typeof v === 'number' ? v : 0);
    return {
      id: str(n.id),
      name: str(n.name) || '(未命名)',
      ocid: str(n.id),
      tenant: tenantName,
      region: str(n.region),
      ad: str(n.zone) || '-',
      shape: str(n.spec) || '-',
      ocpus: num(n.cpu),
      memoryGb: num(n.memory_gb),
      publicIp: str(n.public_ip),
      privateIp: str(n.private_ip),
      status: toStatus(str(n.status)),
      createdAt: str(n.created_at),
      provider,
    };
  }
  return {
    id: b.id,
    name: b.display_name || '(未命名)',
    ocid: b.id,
    tenant: tenantName,
    region: b.region,
    ad: b.availability_domain || '-',
    shape: b.shape || '-',
    ocpus: b.ocpus ?? 0,
    memoryGb: b.memory_in_gbs ?? 0,
    publicIp: b.public_ip || '',
    privateIp: b.private_ip || '',
    status: toStatus(b.lifecycle_state),
    createdAt: b.time_created || '',
    provider: 'oci',
  };
}

/** 实例列表（真实 OCI 查询） */
export async function listInstances(
  q: InstanceQuery,
  tenantName: string,
): Promise<{ items: Instance[]; total: number }> {
  const resp = await api.get('/api/v1/instances', { params: q });
  const data = resp.data as { items?: BackendInstance[]; total?: number };
  const items = (data.items ?? []).map((b) => toInstance(b, tenantName));
  return { items, total: data.total ?? items.length };
}

/** 实例详情：列表字段 + 详情专有字段 */
export interface SecurityGroupRef {
  id: string;
  name: string;
}

export interface VnicInfo {
  id: string;
  subnetId: string | null;
  subnetName: string | null;
  mac: string | null;
  hostname: string | null;
  publicIp: string | null;
  privateIp: string | null;
  ipv6Addresses: string[];
  nsgs: SecurityGroupRef[];
  securityLists: SecurityGroupRef[];
}

export interface VolumeInfo {
  id: string;
  displayName: string | null;
  sizeInGbs: number | null;
}

export interface InstanceDetail extends Instance {
  compartmentId: string;
  compartmentName: string;
  availabilityDomainFull: string;
  faultDomain: string;
  imageId: string;
  vnic: VnicInfo | null;
  bootVolume: VolumeInfo | null;
  dataVolumes: VolumeInfo[];
  definedTags: Record<string, Record<string, unknown>> | null;
  freeformTags: Record<string, string> | null;
  /** Shape 理论网络带宽（Gbps，OCI 官方控制台同款，走 list_shapes 实时查询） */
  networkBandwidthGbps: number | null;
}

/** 实例详情（真实 OCI 查询） */
export async function getInstanceDetail(tenantId: number, instanceId: string): Promise<InstanceDetail> {
  const resp = await api.get(`/api/v1/instances/${encodeURIComponent(instanceId)}`, {
    params: { tenant_id: tenantId },
  });
  const b = resp.data as BackendInstance & {
    compartment_id?: string;
    compartment_name?: string;
    availability_domain_full?: string;
    fault_domain?: string | null;
    image_id?: string | null;
    vnic?: {
      id: string; subnet_id: string | null; subnet_name: string | null;
      mac: string | null; hostname: string | null;
      public_ip: string | null; private_ip: string | null;
      ipv6_addresses?: string[];
      security_groups?: { nsgs: { id: string; name: string }[]; security_lists: { id: string; name: string }[] };
    } | null;
    boot_volume?: { id: string; display_name: string | null; size_in_gbs: number | null } | null;
    data_volumes?: { id: string; display_name: string | null; size_in_gbs: number | null }[];
    defined_tags?: Record<string, Record<string, unknown>> | null;
    freeform_tags?: Record<string, string> | null;
    network_bandwidth_gbps?: number | null;
  };
  const base = toInstance(b, '');
  const toVol = (v: { id: string; display_name: string | null; size_in_gbs: number | null }): VolumeInfo => ({
    id: v.id, displayName: v.display_name, sizeInGbs: v.size_in_gbs,
  });
  return {
    ...base,
    compartmentId: b.compartment_id ?? '',
    compartmentName: b.compartment_name ?? '',
    availabilityDomainFull: b.availability_domain_full ?? base.ad,
    faultDomain: b.fault_domain ?? '-',
    imageId: b.image_id ?? '-',
    vnic: b.vnic ? {
      id: b.vnic.id,
      subnetId: b.vnic.subnet_id,
      subnetName: b.vnic.subnet_name,
      mac: b.vnic.mac,
      hostname: b.vnic.hostname,
      publicIp: b.vnic.public_ip,
      privateIp: b.vnic.private_ip,
      ipv6Addresses: b.vnic.ipv6_addresses ?? [],
      nsgs: b.vnic.security_groups?.nsgs ?? [],
      securityLists: b.vnic.security_groups?.security_lists ?? [],
    } : null,
    bootVolume: b.boot_volume ? toVol(b.boot_volume) : null,
    dataVolumes: (b.data_volumes ?? []).map(toVol),
    definedTags: b.defined_tags ?? null,
    freeformTags: b.freeform_tags ?? null,
    networkBandwidthGbps: b.network_bandwidth_gbps ?? null,
  };
}

export type PowerOp = 'start' | 'stop' | 'reboot';

/** 电源操作：start | stop | reboot */
export async function powerInstance(tenantId: number, instanceId: string, action: PowerOp): Promise<void> {
  await api.post(`/api/v1/instances/${encodeURIComponent(instanceId)}/power`, {
    tenant_id: tenantId,
    action,
  });
}

/** 改实例名 */
export async function renameInstance(tenantId: number, instanceId: string, displayName: string): Promise<string> {
  const resp = await api.put(`/api/v1/instances/${encodeURIComponent(instanceId)}/name`, {
    tenant_id: tenantId,
    display_name: displayName,
  });
  return (resp.data as { display_name?: string }).display_name ?? displayName;
}

/** 终止实例（默认保留引导卷） */
export async function terminateInstance(
  tenantId: number,
  instanceId: string,
  preserveBootVolume = true,
): Promise<void> {
  await api.post(`/api/v1/instances/${encodeURIComponent(instanceId)}/terminate`, {
    tenant_id: tenantId,
    preserve_boot_volume: preserveBootVolume,
  });
}

export interface ChangeShapeInput {
  shape: string;
  ocpus?: number | null;
  memory_in_gbs?: number | null;
}

/** 改实例 Shape（实例需处于关机状态；Flex 机型需带 OCPU/内存） */
export async function changeShape(
  tenantId: number,
  instanceId: string,
  input: ChangeShapeInput,
): Promise<void> {
  await api.put(`/api/v1/instances/${encodeURIComponent(instanceId)}/shape`, {
    tenant_id: tenantId,
    shape: input.shape,
    ocpus: input.ocpus ?? null,
    memory_in_gbs: input.memory_in_gbs ?? null,
  });
}
