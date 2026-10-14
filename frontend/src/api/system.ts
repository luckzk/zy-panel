import { api } from './client';

export interface LogItem {
  id: number;
  user_id: number | null;
  action: string;
  detail: string;
  created_at: string | null;
}

/** 操作审计日志（真实数据） */
export async function getLogs(limit = 100): Promise<LogItem[]> {
  const resp = await api.get('/api/v1/system/logs', { params: { limit } });
  return (resp.data ?? []) as LogItem[];
}

/** 导出加密备份（真实文件下载） */
export async function downloadBackup(): Promise<void> {
  const resp = await api.get('/api/v1/system/backup', { responseType: 'blob' });
  const disposition = (resp.headers?.['content-disposition'] as string) || '';
  const m = disposition.match(/filename=([^;]+)/);
  const filename = (m?.[1] ?? `oci-panel-backup.bin`).trim().replace(/"/g, '');
  const url = URL.createObjectURL(resp.data as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** 从加密备份文件恢复（真实接口） */
export async function restoreBackup(file: File): Promise<{ restored: boolean; counts: Record<string, number> }> {
  const form = new FormData();
  form.append('file', file);
  const resp = await api.post('/api/v1/system/restore', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return resp.data as { restored: boolean; counts: Record<string, number> };
}

/** 后端版本信息 */
export async function getVersion(): Promise<{ version: string; name: string }> {
  const resp = await api.get('/api/v1/system/version');
  return resp.data as { version: string; name: string };
}

export interface TgBotConfig {
  enabled: boolean;
  token: string; // 已脱敏（***）或空
  chat_ids: string[];
}

/** TG 运维机器人配置 */
export async function getTgBotConfig(): Promise<TgBotConfig> {
  const resp = await api.get('/api/v1/system/tg-bot');
  return resp.data as TgBotConfig;
}

/** 更新 TG 运维机器人配置 */
export async function updateTgBotConfig(enabled: boolean, chat_ids: string): Promise<void> {
  await api.post('/api/v1/system/tg-bot', { enabled, chat_ids });
}

export interface UpdateCheck {
  current_version: string;
  feed_url: string;
  latest_version: string | null;
  has_update: boolean;
  notes: string;
  download_url: string | null;
}

export interface UpdateApplyResult {
  applied: boolean;
  backend_changed: boolean;
  frontend_changed: boolean;
  backup_dir: string;
  notes: string;
  restart: string;
}

/** 检查更新 */
export async function checkUpdate(): Promise<UpdateCheck> {
  const resp = await api.get('/api/v1/system/update/check');
  return resp.data as UpdateCheck;
}

/** 配置更新源（GitHub Releases API） */
export async function setUpdateFeed(feed_url: string): Promise<void> {
  await api.post('/api/v1/system/update/feed', { feed_url });
}

/** 上传更新包并应用 */
export async function applyUpdate(file: File): Promise<UpdateApplyResult> {
  const form = new FormData();
  form.append('file', file);
  const resp = await api.post('/api/v1/system/update/apply', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  });
  return resp.data as UpdateApplyResult;
}

export interface GithubUpdateConfig {
  repo: string;
  branch: string;
  has_token: boolean;
  last_applied_sha: string;
}

export interface GithubUpdateCheck {
  current_version: string;
  repo: string;
  branch: string;
  has_token: boolean;
  last_applied_sha: string;
  latest_sha: string;
  latest_date: string;
  latest_message: string;
  remote_version: string;
  has_update: boolean;
  notes: string;
}

export interface GithubApplyResult extends UpdateApplyResult {
  github: { repo: string; branch: string; sha: string; message: string };
}

/** 获取 GitHub 更新配置 */
export async function getGithubUpdateConfig(): Promise<GithubUpdateConfig> {
  const resp = await api.get('/api/v1/system/update/github/config');
  return resp.data as GithubUpdateConfig;
}

/** 保存 GitHub 更新配置 */
export async function saveGithubUpdateConfig(
  repo: string, branch: string, token: string, clear_token = false,
): Promise<GithubUpdateConfig> {
  const resp = await api.post('/api/v1/system/update/github/config', { repo, branch, token, clear_token });
  return resp.data as GithubUpdateConfig;
}

/** 检查 GitHub 仓库更新 */
export async function checkGithubUpdate(): Promise<GithubUpdateCheck> {
  const resp = await api.get('/api/v1/system/update/github/check');
  return resp.data as GithubUpdateCheck;
}

/** 从 GitHub 拉取并应用更新（会重启后端） */
export async function applyGithubUpdate(): Promise<GithubApplyResult> {
  const resp = await api.post('/api/v1/system/update/github/apply', {}, { timeout: 300000 });
  return resp.data as GithubApplyResult;
}

export interface DailyReportConfig {
  enabled: boolean;
  time: string;
  last_sent: string;
}

/** 每日健康报告配置 */
export async function getDailyReportConfig(): Promise<DailyReportConfig> {
  const resp = await api.get('/api/v1/system/daily-report');
  return resp.data as DailyReportConfig;
}

/** 更新每日健康报告配置 */
export async function updateDailyReportConfig(enabled: boolean, time: string): Promise<DailyReportConfig> {
  const resp = await api.post('/api/v1/system/daily-report', { enabled, time });
  return resp.data as DailyReportConfig;
}

/** 立即发送一次每日报告（测试用，不影响定时任务） */
export async function sendDailyReportNow(): Promise<{ channels_ok?: number; channels_failed?: number; note?: string }> {
  const resp = await api.post('/api/v1/system/daily-report/send');
  return resp.data as { channels_ok?: number; channels_failed?: number; note?: string };
}
