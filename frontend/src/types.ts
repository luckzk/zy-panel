/** 业务实体 TypeScript 类型与常量（无任何 mock 数据） */

/** 租户配置 */
export interface Tenant {
  id: string;
  name: string;
  region: string;
  tenancyId: string;
  userId: string;
  fingerprint: string;
  status: 'active' | 'error';
}

/** 云实例 */
export type InstanceStatus = 'RUNNING' | 'STOPPED' | 'STARTING' | 'STOPPING' | 'TERMINATED';
export interface Instance {
  id: string;
  name: string;
  ocid: string;
  tenant: string;
  provider?: string; // oci / aliyun（多云归一化）
  region: string;
  ad: string;
  shape: string;
  ocpus: number;
  memoryGb: number;
  publicIp: string;
  privateIp: string;
  status: InstanceStatus;
  createdAt: string;
}

/** 抢机任务状态机 */
export type SnatchStatus = 'pending' | 'running' | 'paused' | 'success' | 'failed';
export interface SnatchTask {
  id: string;
  name: string;
  tenant: string;
  region: string;
  ad: string;
  shape: string;
  image: string;
  status: SnatchStatus;
  attempts: number;
  intervalSec: number;
  createdAt: string;
  recentLogs: string[];
}

/** 安全组规则 */
export interface SecurityRule {
  id: string;
  direction: 'ingress' | 'egress';
  protocol: string;
  ports: string;
  source: string;
  description: string;
}

/** 引导卷 */
export interface Volume {
  id: string;
  name: string;
  ocid: string;
  instance: string;
  sizeGb: number;
  status: string;
}

/** DNS 记录 */
export interface DnsRecord {
  id: string;
  domain: string;
  type: 'A' | 'AAAA' | 'CNAME' | 'TXT';
  value: string;
  ttl: number;
  remark: string;
}

/** 换 IP 记录 */
export interface IpChangeRecord {
  id: string;
  instance: string;
  oldIp: string;
  newIp: string;
  status: 'success' | 'failed' | 'running';
  createdAt: string;
}

/** Region 中文名（与 REGIONS 同源，供展示用） */
export const REGION_CN: Record<string, string> = {
  'ap-tokyo-1': '东京', 'ap-chiyoda-1': '千代田', 'ap-ibaraki-1': '茨城', 'ap-osaka-1': '大阪',
  'ap-seoul-1': '首尔', 'ap-seoul-2': '首尔 2', 'ap-chuncheon-1': '春川', 'ap-chuncheon-2': '春川 2',
  'ap-suwon-1': '水原', 'ap-singapore-1': '新加坡', 'ap-singapore-2': '新加坡 2',
  'ap-mumbai-1': '孟买', 'ap-hyderabad-1': '海得拉巴', 'ap-delhi-1': '德里',
  'ap-sydney-1': '悉尼', 'ap-melbourne-1': '墨尔本', 'ap-batam-1': '巴淡岛', 'ap-kulai-2': '古来',
  'us-ashburn-1': '阿什本', 'us-ashburn-2': '阿什本 2', 'us-phoenix-1': '凤凰城',
  'us-chicago-1': '芝加哥', 'us-sanjose-1': '圣何塞', 'us-newark-1': '纽瓦克',
  'us-saltlake-2': '盐湖城', 'us-somerset-1': '萨默塞特', 'us-thames-1': '泰晤士',
  'ca-montreal-1': '蒙特利尔', 'ca-toronto-1': '多伦多',
  'mx-queretaro-1': '克雷塔罗', 'mx-monterrey-1': '蒙特雷',
  'sa-saopaulo-1': '圣保罗', 'sa-vinhedo-1': '维涅杜', 'sa-riodejaneiro-1': '里约热内卢',
  'sa-santiago-1': '圣地亚哥', 'sa-valparaiso-1': '瓦尔帕莱索', 'sa-bogota-1': '波哥大',
  'eu-frankfurt-1': '法兰克福', 'eu-frankfurt-2': '法兰克福 2', 'eu-zurich-1': '苏黎世',
  'eu-amsterdam-1': '阿姆斯特丹', 'eu-milan-1': '米兰', 'eu-turin-1': '都灵',
  'eu-paris-1': '巴黎', 'eu-marseille-1': '马赛', 'eu-madrid-1': '马德里',
  'eu-madrid-2': '马德里 2', 'eu-madrid-3': '马德里 3', 'eu-stockholm-1': '斯德哥尔摩',
  'eu-budapest-1': '布达佩斯', 'eu-crissier-1': '克里西耶', 'eu-jovanovac-1': '约瓦诺瓦茨',
  'uk-london-1': '伦敦', 'uk-cardiff-1': '卡迪夫', 'il-jerusalem-1': '耶路撒冷',
  'me-jeddah-1': '吉达', 'me-riyadh-1': '利雅得', 'me-dubai-1': '迪拜',
  'me-abudhabi-1': '阿布扎比', 'me-abudhabi-2': '阿布扎比 2', 'me-abudhabi-3': '阿布扎比 3',
  'me-abudhabi-4': '阿布扎比 4', 'me-alain-1': '艾因', 'me-ibri-1': '伊卜里',
  'me-alrayyan-1': '赖扬',
  'af-johannesburg-1': '约翰内斯堡', 'af-casablanca-1': '卡萨布兰卡',
};

/** Region 下拉选项：运行时从后端 /meta/regions 获取（OCI SDK 权威列表），此处不写死。 */

/** Shape 下拉选项：运行时从后端 /meta/shapes 实时获取（按租户+compartment），此处不写死。 */
