import { api } from './client';

export interface IpMapPoint {
  tenant_name: string;
  instance_name: string;
  ip: string;
  country: string | null;
  city: string | null;
  lat: number;
  lon: number;
  isp: string | null;
}

/** 全球实例分布：所有租户实例公网 IP 的归属地打点（真实数据，无数据返回空数组） */
export async function getIpMap(): Promise<IpMapPoint[]> {
  const resp = await api.get('/api/v1/ipinfo/map');
  const data = resp.data as IpMapPoint[] | null;
  return data ?? [];
}

/** 强制刷新 IP 归属地缓存（绕过 30 天 TTL） */
export async function refreshIpMap(): Promise<IpMapPoint[]> {
  const resp = await api.post('/api/v1/ipinfo/refresh');
  const data = resp.data as IpMapPoint[] | null;
  return data ?? [];
}
