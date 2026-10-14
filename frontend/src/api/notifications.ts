import { api } from './client';

/** 渠道类型 */
export type NotificationType = 'telegram' | 'email';

/** 后端通知渠道（config 已脱敏） */
export interface NotificationChannel {
  id: number;
  type: NotificationType;
  name: string;
  config: Record<string, string>;
  enabled: boolean;
  created_at: string | null;
}

export interface NotificationCreate {
  type: NotificationType;
  name: string;
  config_json: Record<string, unknown>;
  enabled: boolean;
}

export interface NotificationUpdate {
  name?: string;
  config_json?: Record<string, unknown>;
  enabled?: boolean;
}

/** 测试发送结果 */
export interface TestSendResult {
  ok: boolean;
  msg: string;
  id?: number;
  name?: string;
  type?: string;
}

/** 渠道列表 */
export async function listNotifications(): Promise<NotificationChannel[]> {
  const resp = await api.get('/api/v1/notifications');
  return (resp.data ?? []) as NotificationChannel[];
}

/** 创建渠道 */
export async function createNotification(body: NotificationCreate): Promise<NotificationChannel> {
  const resp = await api.post('/api/v1/notifications', body);
  return resp.data as NotificationChannel;
}

/** 更新渠道（config_json 与已有配置浅合并） */
export async function updateNotification(id: number, body: NotificationUpdate): Promise<NotificationChannel> {
  const resp = await api.put(`/api/v1/notifications/${id}`, body);
  return resp.data as NotificationChannel;
}

/** 删除渠道 */
export async function deleteNotification(id: number): Promise<void> {
  await api.delete(`/api/v1/notifications/${id}`);
}

/** 发送测试消息 */
export async function testNotification(id: number): Promise<TestSendResult> {
  const resp = await api.post(`/api/v1/notifications/${id}/test`);
  return resp.data as TestSendResult;
}
