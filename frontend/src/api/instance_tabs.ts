import { api } from './client';

/** 实例详情各 Tab 接口（对标 OCI Console 实例详情页） */

export interface LaunchOptions {
  network_type: string | null;
  boot_volume_type: string | null;
  remote_data_volume_type: string | null;
  firmware: string | null;
  is_pv_encryption_in_transit_enabled: boolean | null;
  is_secure_boot_enabled: boolean | null;
  is_measured_boot_enabled: boolean | null;
  is_trusted_platform_module_enabled: boolean | null;
  is_consistent_volume_naming_enabled: boolean | null;
}

export interface DetailExtra {
  launch_options: LaunchOptions | null;
  capacity_type: string;
  time_created: string | null;
  image: { id: string; display_name: string | null; operating_system: string | null; operating_system_version: string | null } | null;
  ssh_username: string;
}

export interface NetworkTab {
  route_table_name: string;
  internal_fqdn: string;
  vnic_attachments: { id: string; vnic_id: string; display_name: string; lifecycle_state: string; nic_index: number | null; time_created: string | null }[];
}

export interface BootVolumeExt {
  id: string;
  display_name: string | null;
  size_in_gbs: number | null;
  lifecycle_state: string | null;
  is_transit_encryption_enabled: boolean | null;
  time_created: string | null;
  attached_time: string | null;
  source_image: string;
  volume_type: string | null;
}

export interface DataVolumeExt {
  id: string;
  display_name: string | null;
  size_in_gbs: number | null;
  lifecycle_state: string | null;
  volume_type: string | null;
  vpus_per_gb: number | null;
  is_transit_encryption_enabled: boolean | null;
  device: string | null;
  attachment_type: string | null;
  is_read_only: boolean | null;
  time_created: string | null;
  attached_time: string | null;
}

export interface StorageTab {
  boot_volume: BootVolumeExt | null;
  data_volumes: DataVolumeExt[];
}

export interface SecurityTab {
  security_list_rules: { id: string; name: string; rules: { direction: string; protocol: string; source: string; source_type: string; description: string }[] }[];
}

export interface ManagementTab {
  maintenance_events: { id: string; display_name: string; maintenance_category: string; maintenance_reason: string; lifecycle_state: string; time_started: string | null; time_finished: string | null; time_window_start: string | null }[];
}

export interface AgentPlugins {
  plugins: { name: string; status: string; time_last_updated: string | null }[];
  available: boolean;
  note: string;
}

export interface WorkRequests {
  work_requests: { id: string; operation_type: string; status: string; percent_complete: number | null; time_accepted: string | null; time_finished: string | null }[];
}

export interface MetricChart {
  metric: string;
  title: string;
  points: { time: string | null; value: number }[];
  error?: string;
}

const base = (tenantId: number, instanceId: string, suffix: string, params?: Record<string, unknown>) =>
  api.get(`/api/v1/instances/${instanceId}/tabs/${suffix}`, { params: { tenant_id: tenantId, ...params } }).then((r) => r.data);

export const getDetailExtra = (t: number, id: string) => base(t, id, 'detail-extra').then((d) => d as DetailExtra);
export const getNetworkTab = (t: number, id: string) => base(t, id, 'network').then((d) => d as NetworkTab);
export const getStorageTab = (t: number, id: string) => base(t, id, 'storage').then((d) => d as StorageTab);
export const getSecurityTab = (t: number, id: string) => base(t, id, 'security').then((d) => d as SecurityTab);
export const getManagementTab = (t: number, id: string) => base(t, id, 'management').then((d) => d as ManagementTab);
export const getAgentPlugins = (t: number, id: string) => base(t, id, 'agent-plugins').then((d) => d as AgentPlugins);
export const getWorkRequests = (t: number, id: string) => base(t, id, 'work-requests').then((d) => d as WorkRequests);
export const getMetricsTab = (t: number, id: string, hours = 6) => base(t, id, 'metrics', { hours }).then((d) => d as { charts: MetricChart[] });

/** 操作类 */
export const createCustomImage = (t: number, id: string, display_name: string) =>
  api.post(`/api/v1/instances/${id}/custom-image`, { tenant_id: t, display_name }).then((r) => r.data);
export const changeInstanceCompartment = (t: number, id: string, compartment_id: string) =>
  api.post(`/api/v1/instances/${id}/change-compartment`, { tenant_id: t, compartment_id }).then((r) => r.data);
export const diagnosticAction = (t: number, id: string, action: 'SENDDIAGNOSTICINTERRUPT' | 'DIAGNOSTICREBOOT') =>
  api.post(`/api/v1/instances/${id}/diagnostic`, { tenant_id: t, action }).then((r) => r.data);
export const runInstanceCommand = (t: number, id: string, content: string, display_name?: string) =>
  api.post(`/api/v1/instances/${id}/run-command`, { tenant_id: t, content, display_name: display_name || '' }).then((r) => r.data);
export const getRunCommandResult = (t: number, id: string, command_id: string) =>
  api.get(`/api/v1/instances/${id}/run-command/${command_id}`, { params: { tenant_id: t } }).then((r) => r.data);
export const captureConsoleHistory = (t: number, id: string) =>
  api.post(`/api/v1/instances/${id}/console-history/capture`, { tenant_id: t }).then((r) => r.data);
export const getConsoleHistoryContent = (t: number, id: string, history_id: string) =>
  api.get(`/api/v1/instances/${id}/console-history/${history_id}/content`, { params: { tenant_id: t } }).then((r) => r.data);
