import { api } from './client';

/** IAM 用户管理（全部走后端 /api/v1/iam，实时 OCI 接口） */
export interface IamUser {
  id: string; name: string; description: string; email: string;
  lifecycle_state: string; time_created: string | null; is_mfa_activated: boolean;
}
export interface ApiKey {
  fingerprint: string; key_id: string; time_created: string | null; lifecycle_state: string;
}
export interface IamGroup {
  id: string; name: string; description: string; lifecycle_state: string; time_created: string | null;
}
export interface GroupMember { membership_id: string; user_id: string; group_id: string; lifecycle_state: string }
export interface AuthToken { id: string; description: string; time_created: string | null; time_expires: string | null; lifecycle_state: string }
export interface SecretKey { id: string; display_name: string; time_created: string | null; time_expires: string | null; lifecycle_state: string }
export interface SmtpCredential { id: string; username: string; description: string; time_created: string | null; time_expires: string | null; lifecycle_state: string }
export interface MfaDevice { id: string; time_created: string | null; lifecycle_state: string }

const asArray = <T>(data: unknown): T[] => (Array.isArray(data) ? (data as T[]) : []);

/* 用户 */
export async function listIamUsers(tenantId: number): Promise<IamUser[]> {
  const resp = await api.get('/api/v1/iam/users', { params: { tenant_id: tenantId } });
  return asArray<IamUser>(resp.data);
}
export async function createIamUser(tenantId: number, body: { name: string; description?: string; email?: string }) {
  const resp = await api.post(`/api/v1/iam/users?tenant_id=${tenantId}`, body);
  return resp.data;
}
export async function updateIamUser(tenantId: number, userId: string, body: { description?: string; email?: string }) {
  const resp = await api.put(`/api/v1/iam/users/${userId}?tenant_id=${tenantId}`, body);
  return resp.data;
}
export async function deleteIamUser(tenantId: number, userId: string) {
  const resp = await api.delete(`/api/v1/iam/users/${userId}?tenant_id=${tenantId}`);
  return resp.data;
}

/* API 密钥 */
export async function listApiKeys(tenantId: number, userId: string): Promise<ApiKey[]> {
  const resp = await api.get(`/api/v1/iam/users/${userId}/api-keys`, { params: { tenant_id: tenantId } });
  return asArray<ApiKey>(resp.data);
}
export async function uploadApiKey(tenantId: number, userId: string, publicKeyPem: string) {
  const resp = await api.post(`/api/v1/iam/users/${userId}/api-keys?tenant_id=${tenantId}`, { public_key_pem: publicKeyPem });
  return resp.data;
}
export async function deleteApiKey(tenantId: number, userId: string, fingerprint: string) {
  const resp = await api.delete(`/api/v1/iam/users/${userId}/api-keys/${fingerprint}?tenant_id=${tenantId}`);
  return resp.data;
}

/* 用户组 */
export async function listIamGroups(tenantId: number): Promise<IamGroup[]> {
  const resp = await api.get('/api/v1/iam/groups', { params: { tenant_id: tenantId } });
  return asArray<IamGroup>(resp.data);
}
export async function createIamGroup(tenantId: number, body: { name: string; description?: string }) {
  const resp = await api.post(`/api/v1/iam/groups?tenant_id=${tenantId}`, body);
  return resp.data;
}
export async function deleteIamGroup(tenantId: number, groupId: string) {
  const resp = await api.delete(`/api/v1/iam/groups/${groupId}?tenant_id=${tenantId}`);
  return resp.data;
}
export async function listGroupMembers(tenantId: number, groupId: string): Promise<GroupMember[]> {
  const resp = await api.get(`/api/v1/iam/groups/${groupId}/members`, { params: { tenant_id: tenantId } });
  return asArray<GroupMember>(resp.data);
}
export async function addGroupMember(tenantId: number, groupId: string, userId: string) {
  const resp = await api.post(`/api/v1/iam/groups/${groupId}/members?tenant_id=${tenantId}`, { user_id: userId });
  return resp.data;
}
export async function removeGroupMember(tenantId: number, groupId: string, membershipId: string) {
  const resp = await api.delete(`/api/v1/iam/groups/${groupId}/members/${membershipId}?tenant_id=${tenantId}`);
  return resp.data;
}

/* 令牌与凭证 */
export async function listAuthTokens(tenantId: number, userId: string): Promise<AuthToken[]> {
  const resp = await api.get(`/api/v1/iam/users/${userId}/auth-tokens`, { params: { tenant_id: tenantId } });
  return asArray<AuthToken>(resp.data);
}
export async function createAuthToken(tenantId: number, userId: string, description?: string) {
  const resp = await api.post(`/api/v1/iam/users/${userId}/auth-tokens?tenant_id=${tenantId}`, { description });
  return resp.data as { id: string; token: string };
}
export async function deleteAuthToken(tenantId: number, userId: string, tokenId: string) {
  const resp = await api.delete(`/api/v1/iam/users/${userId}/auth-tokens/${tokenId}?tenant_id=${tenantId}`);
  return resp.data;
}
export async function listSecretKeys(tenantId: number, userId: string): Promise<SecretKey[]> {
  const resp = await api.get(`/api/v1/iam/users/${userId}/secret-keys`, { params: { tenant_id: tenantId } });
  return asArray<SecretKey>(resp.data);
}
export async function createSecretKey(tenantId: number, userId: string, displayName?: string) {
  const resp = await api.post(`/api/v1/iam/users/${userId}/secret-keys?tenant_id=${tenantId}`, { display_name: displayName });
  return resp.data as { id: string; key: string };
}
export async function deleteSecretKey(tenantId: number, userId: string, keyId: string) {
  const resp = await api.delete(`/api/v1/iam/users/${userId}/secret-keys/${keyId}?tenant_id=${tenantId}`);
  return resp.data;
}
export async function listSmtpCredentials(tenantId: number, userId: string): Promise<SmtpCredential[]> {
  const resp = await api.get(`/api/v1/iam/users/${userId}/smtp-credentials`, { params: { tenant_id: tenantId } });
  return asArray<SmtpCredential>(resp.data);
}
export async function createSmtpCredential(tenantId: number, userId: string, description?: string) {
  const resp = await api.post(`/api/v1/iam/users/${userId}/smtp-credentials?tenant_id=${tenantId}`, { description });
  return resp.data as { id: string; username: string; password: string };
}
export async function deleteSmtpCredential(tenantId: number, userId: string, credId: string) {
  const resp = await api.delete(`/api/v1/iam/users/${userId}/smtp-credentials/${credId}?tenant_id=${tenantId}`);
  return resp.data;
}
export async function listMfaDevices(tenantId: number, userId: string): Promise<MfaDevice[]> {
  const resp = await api.get(`/api/v1/iam/users/${userId}/mfa-devices`, { params: { tenant_id: tenantId } });
  return asArray<MfaDevice>(resp.data);
}
export async function deleteMfaDevice(tenantId: number, userId: string, deviceId: string) {
  const resp = await api.delete(`/api/v1/iam/users/${userId}/mfa-devices/${deviceId}?tenant_id=${tenantId}`);
  return resp.data;
}
