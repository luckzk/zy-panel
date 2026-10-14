/** 云厂商注册表：加厂商只加配置，不改表单/列表代码。 */

export interface CredentialField {
  key: string;
  label: string;
  type?: 'input' | 'password' | 'textarea' | 'region-select';
  required?: boolean;
  placeholder?: string;
  help?: string;
}

export interface ProviderMeta {
  id: string;
  name: string;
  short: string;
  color: string;
  credentialFields: CredentialField[];
  /** 实例详情页 Tab（按厂商条件渲染） */
  detailTabs: string[];
}

export const PROVIDERS: Record<string, ProviderMeta> = {
  oci: {
    id: 'oci',
    name: 'Oracle Cloud',
    short: 'OCI',
    color: '#C74634',
    credentialFields: [
      { key: 'tenancy_ocid', label: 'Tenancy OCID', required: true },
      { key: 'user_ocid', label: 'User OCID', required: true },
      { key: 'fingerprint', label: 'API Key 指纹', required: true },
      { key: 'private_key', label: '私钥 PEM', type: 'textarea', required: true },
      { key: 'region', label: 'Region', type: 'region-select', required: true },
    ],
    detailTabs: ['detail', 'network', 'storage', 'security', 'management', 'osmgmt', 'monitor', 'work', 'tags'],
  },
  aliyun: {
    id: 'aliyun',
    name: '阿里云',
    short: 'ALI',
    color: '#FF6A00',
    credentialFields: [
      { key: 'access_key_id', label: 'AccessKey ID', required: true, placeholder: 'LTAI...' },
      { key: 'access_key_secret', label: 'AccessKey Secret', type: 'password', required: true },
      { key: 'aliyun_region', label: '地域', type: 'region-select', required: true, help: '国内/国际靠地域区分' },
    ],
    detailTabs: ['detail', 'network', 'security', 'monitor'],
  },
};

export function getProviderMeta(id: string | undefined | null): ProviderMeta {
  return PROVIDERS[id || 'oci'] || PROVIDERS.oci;
}

export function providerOptions(): { value: string; label: string }[] {
  return Object.values(PROVIDERS).map((p) => ({ value: p.id, label: p.name }));
}
