import { api } from './client';

/** MFA 绑定结果（后端 POST /auth/mfa/setup 返回） */
export interface MfaSetupResult {
  secret: string;
  otpauth_uri: string;
  /** PNG 二维码的 base64 data URI，可直接用作 <img src> */
  qr_data_uri: string;
}

export interface MfaStatus {
  mfa_enabled: boolean;
  has_secret: boolean;
}

export interface MeInfo {
  username: string;
  is_admin: boolean;
  mfa_enabled: boolean;
}

/** 当前登录用户信息 */
export async function me(): Promise<MeInfo> {
  const resp = await api.get('/api/v1/auth/me');
  return resp.data as MeInfo;
}

/** 当前用户 MFA 状态 */
export async function mfaStatus(): Promise<MfaStatus> {
  const resp = await api.get('/api/v1/auth/mfa/status');
  return resp.data as MfaStatus;
}

/** 生成 MFA 绑定二维码（旧密钥会被新密钥覆盖，需重新绑定） */
export async function mfaSetup(): Promise<MfaSetupResult> {
  const resp = await api.post('/api/v1/auth/mfa/setup');
  return resp.data as MfaSetupResult;
}

/** 绑定确认：验证码正确则启用 MFA */
export async function mfaVerify(code: string): Promise<void> {
  await api.post('/api/v1/auth/mfa/verify', { code });
}

/** 关闭 MFA：验证码正确则解绑 */
export async function mfaDisable(code: string): Promise<void> {
  await api.post('/api/v1/auth/mfa/disable', { code });
}

/** 修改当前用户密码 */
export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  await api.post('/api/v1/auth/change-password', {
    old_password: oldPassword,
    new_password: newPassword,
  });
}
