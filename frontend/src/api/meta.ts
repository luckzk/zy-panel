import { api } from './client';

/** 元数据（全部来自 OCI SDK 或实时接口，不写死） */
export interface Region { id: string }
export interface Compartment { id: string; name: string; description: string }
export interface AvailabilityDomain { name: string }
export interface Shape { shape: string; ocpus: number | null; memory_in_gbs: number | null; is_flex: boolean }
export interface Image { id: string; display_name: string; operating_system: string; operating_system_version: string }
export interface Subnet { id: string; display_name: string; cidr_block: string; availability_domain: string }
export interface BootVolume {
  id: string;
  display_name: string;
  size_in_gbs: number;
  availability_domain: string;
  lifecycle_state: string;
  time_created: string | null;
}

const asArray = <T>(data: unknown): T[] => (Array.isArray(data) ? (data as T[]) : []);

/** 全部商业 Region（OCI SDK 权威列表，无需租户） */
export async function getRegions(): Promise<Region[]> {
  const resp = await api.get('/api/v1/meta/regions');
  return asArray<Region>(resp.data);
}

/** 某租户下（含子级）的 compartment 列表（实时） */
export async function getCompartments(tenantId: number, compartmentId?: string): Promise<Compartment[]> {
  const resp = await api.get('/api/v1/meta/compartments', {
    params: { tenant_id: tenantId, compartment_id: compartmentId },
  });
  return asArray<Compartment>(resp.data);
}

/** 某租户 home region 的可用域（实时） */
export async function getAvailabilityDomains(tenantId: number): Promise<AvailabilityDomain[]> {
  const resp = await api.get('/api/v1/meta/availability-domains', { params: { tenant_id: tenantId } });
  return asArray<AvailabilityDomain>(resp.data);
}

/** 某 compartment 下可用 Shape（实时） */
export async function getShapes(tenantId: number, compartmentId?: string): Promise<Shape[]> {
  const resp = await api.get('/api/v1/meta/shapes', {
    params: { tenant_id: tenantId, compartment_id: compartmentId },
  });
  return asArray<Shape>(resp.data);
}

/** 某 compartment 下可用镜像（实时，按创建时间倒序） */
export async function getImages(tenantId: number, compartmentId?: string): Promise<Image[]> {
  const resp = await api.get('/api/v1/meta/images', {
    params: { tenant_id: tenantId, compartment_id: compartmentId },
  });
  return asArray<Image>(resp.data);
}

/** 某 compartment 下可用子网（实时） */
export async function getSubnets(tenantId: number, compartmentId?: string): Promise<Subnet[]> {
  const resp = await api.get('/api/v1/meta/subnets', {
    params: { tenant_id: tenantId, compartment_id: compartmentId },
  });
  return asArray<Subnet>(resp.data);
}

/** 某 compartment 下可用的引导卷（实时，供从现有引导卷抢机） */
export async function getBootVolumes(
  tenantId: number,
  compartmentId?: string,
  availabilityDomain?: string,
): Promise<BootVolume[]> {
  const resp = await api.get('/api/v1/meta/boot-volumes', {
    params: {
      tenant_id: tenantId,
      compartment_id: compartmentId,
      availability_domain: availabilityDomain || undefined,
    },
  });
  return asArray<BootVolume>(resp.data);
}
