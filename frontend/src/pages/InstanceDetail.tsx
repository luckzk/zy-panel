import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  Dropdown,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Select,
  Skeleton,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  ArrowLeftOutlined,
  DownOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { getInstanceDetail, powerInstance, renameInstance, terminateInstance, type InstanceDetail as Detail } from '../api/instances';
import {
  captureConsoleHistory,
  changeInstanceCompartment,
  createCustomImage,
  diagnosticAction,
  getAgentPlugins,
  getConsoleHistoryContent,
  getDetailExtra,
  getManagementTab,
  getMetricsTab,
  getNetworkTab,
  getSecurityTab,
  getStorageTab,
  getWorkRequests,
  runInstanceCommand,
  type AgentPlugins,
  type DetailExtra,
  type ManagementTab,
  type DataVolumeExt,
  type MetricChart,
  type NetworkTab,
  type SecurityTab,
  type StorageTab,
  type WorkRequests,
} from '../api/instance_tabs';
import { getCompartments } from '../api/meta';
import { attachIpv6 } from '../api/network';
import { disable500M, enable500M, getBoostTask, type BoostTask } from '../api/boost';
import Chart from '../components/Chart';
import SerialConsole from '../components/SerialConsole';
import { getProviderMeta } from '../providers/registry';
import { getAliInstanceMetrics } from '../api/aliyun';
import type { InstanceStatus } from '../types';

/** 实例状态标签颜色 */
const STATUS_COLOR: Record<InstanceStatus, string> = {
  RUNNING: 'success',
  STOPPED: 'error',
  STARTING: 'processing',
  STOPPING: 'warning',
  TERMINATED: 'default',
};

const STATUS_TEXT: Record<InstanceStatus, string> = {
  RUNNING: '运行中',
  STOPPED: '已停止',
  STARTING: '启动中',
  STOPPING: '停止中',
  TERMINATED: '已终止',
};

const { Text, Paragraph } = Typography;

function fmtTime(v: string | null | undefined): string {
  if (!v) return '-';
  try {
    return new Date(v).toLocaleString('zh-CN', { hour12: false });
  } catch {
    return v;
  }
}

function boolTag(v: boolean | null | undefined): React.ReactNode {
  if (v == null) return <Text type="secondary">-</Text>;
  return v ? <Tag color="green">已启用</Tag> : <Tag>已禁用</Tag>;
}

/** 实例详情整页：对标 OCI Console 的 Tab 布局；阿里云走简化归一化视图 */
export default function InstanceDetailPage() {
  const { id = '' } = useParams();
  const [searchParams] = useSearchParams();
  const tenantId = Number(searchParams.get('tenant_id') || 0);
  const provider = searchParams.get('provider') || 'oci';
  const isAliyun = provider === 'aliyun';
  const navigate = useNavigate();

  const [detail, setDetail] = useState<Detail | null>(null);
  const [aliyunDetail, setAliyunDetail] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('detail');

  // 各 Tab 数据（懒加载）
  const [extra, setExtra] = useState<DetailExtra | null>(null);
  const [network, setNetwork] = useState<NetworkTab | null>(null);
  const [storage, setStorage] = useState<StorageTab | null>(null);
  const [security, setSecurity] = useState<SecurityTab | null>(null);
  const [mgmt, setMgmt] = useState<ManagementTab | null>(null);
  const [plugins, setPlugins] = useState<AgentPlugins | null>(null);
  const [workReqs, setWorkReqs] = useState<WorkRequests | null>(null);
  const [metrics, setMetrics] = useState<MetricChart[] | null>(null);
  const [tabLoading, setTabLoading] = useState<Record<string, boolean>>({});
  const [loaded, setLoaded] = useState<Record<string, boolean>>({});

  // 操作类弹窗
  const [opLoading, setOpLoading] = useState(false);
  const [imgModal, setImgModal] = useState(false);
  const [moveModal, setMoveModal] = useState(false);
  const [cmdModal, setCmdModal] = useState(false);
  const [compartments, setCompartments] = useState<{ value: string; label: string }[]>([]);
  const [histId, setHistId] = useState('');
  const [histContent, setHistContent] = useState('');
  const [histLoading, setHistLoading] = useState(false);
  const [form] = Form.useForm();

  const loadDetail = useCallback(async () => {
    if (!tenantId || !id) return;
    setLoading(true);
    try {
      const d = await getInstanceDetail(tenantId, id);
      if (isAliyun) {
        setAliyunDetail(d as unknown as Record<string, unknown>);
        setDetail(null);
      } else {
        setDetail(d);
        setAliyunDetail(null);
      }
    } catch {
      setDetail(null);
      setAliyunDetail(null);
    } finally {
      setLoading(false);
    }
  }, [tenantId, id, isAliyun]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  const loadTab = useCallback(async (key: string) => {
    if (!tenantId || !id || loaded[key] || tabLoading[key]) return;
    setTabLoading((p) => ({ ...p, [key]: true }));
    try {
      switch (key) {
        case 'detail': setExtra(await getDetailExtra(tenantId, id)); break;
        case 'network': setNetwork(await getNetworkTab(tenantId, id)); break;
        case 'storage': setStorage(await getStorageTab(tenantId, id)); break;
        case 'security': setSecurity(await getSecurityTab(tenantId, id)); break;
        case 'management':
          setMgmt(await getManagementTab(tenantId, id));
          setPlugins(await getAgentPlugins(tenantId, id));
          break;
        case 'work': setWorkReqs(await getWorkRequests(tenantId, id)); break;
        case 'monitor': setMetrics((await getMetricsTab(tenantId, id)).charts); break;
        default: break;
      }
      setLoaded((p) => ({ ...p, [key]: true }));
    } catch {
      /* 单 Tab 失败时显示空状态 */
    } finally {
      setTabLoading((p) => ({ ...p, [key]: false }));
    }
  }, [tenantId, id, loaded, tabLoading]);

  useEffect(() => {
    if (detail) loadTab(tab);
  }, [tab, detail, loadTab]);

  const doPower = async (action: 'start' | 'stop' | 'reboot') => {
    setOpLoading(true);
    try {
      await powerInstance(tenantId, id, action);
      message.success('操作已提交');
      setTimeout(loadDetail, 3000);
    } finally {
      setOpLoading(false);
    }
  };

  const doTerminate = async () => {
    setOpLoading(true);
    try {
      await terminateInstance(tenantId, id, true);
      message.success('终止请求已提交');
      navigate('/instances');
    } finally {
      setOpLoading(false);
    }
  };

  if (loading) {
    return (
      <Card>
        <Skeleton active paragraph={{ rows: 10 }} />
      </Card>
    );
  }

  if (!detail && !aliyunDetail) {
    return (
      <Card>
        <Empty description="实例详情加载失败">
          <Button onClick={() => navigate('/instances')}>返回实例列表</Button>
        </Empty>
      </Card>
    );
  }

  // 阿里云：归一化简化视图（Tab 体系后续按 detailTabs 扩展）
  if (isAliyun && aliyunDetail) {
    const a = aliyunDetail;
    const str = (v: unknown) => (typeof v === 'string' ? v : '-');
    const tags = (a.tags as Record<string, string>) || {};
    return (
      <div>
        <Card style={{ marginBottom: 16 }}>
          <Row justify="space-between" align="middle">
            <Col>
              <Space>
                <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/instances')} />
                <div>
                  <Space>
                    <Text strong style={{ fontSize: 20 }}>{str(a.name)}</Text>
                    <Tag color={getProviderMeta('aliyun').color}>阿里云</Tag>
                    <Tag color={(STATUS_COLOR as Record<string, string>)[str(a.status)] || 'default'}>{(STATUS_TEXT as Record<string, string>)[str(a.status)] || str(a.status)}</Tag>
                  </Space>
                  <div><Text type="secondary" style={{ fontSize: 12 }}>实例详细信息 · {str(a.region)}</Text></div>
                </div>
              </Space>
            </Col>
            <Col>
              <Space>
                <Button icon={<PlayCircleOutlined />} loading={opLoading} onClick={() => doPower('start')}>启动</Button>
                <Button icon={<PauseCircleOutlined />} loading={opLoading} onClick={() => doPower('stop')}>停止</Button>
                <Button icon={<ReloadOutlined />} loading={opLoading} onClick={() => doPower('reboot')}>重启</Button>
              </Space>
            </Col>
          </Row>
        </Card>
        <Card title="基本信息">
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="实例 ID" span={2}><Text copyable>{str(a.id)}</Text></Descriptions.Item>
            <Descriptions.Item label="实例规格">{str(a.spec)}</Descriptions.Item>
            <Descriptions.Item label="CPU / 内存">
              {a.cpu ? `${a.cpu} 核` : '-'} / {a.memory_gb ? `${a.memory_gb} GB` : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="地域">{str(a.region)}</Descriptions.Item>
            <Descriptions.Item label="可用区">{str(a.zone)}</Descriptions.Item>
            <Descriptions.Item label="公网 IP">{a.public_ip ? <Text copyable>{str(a.public_ip)}</Text> : '-'}</Descriptions.Item>
            <Descriptions.Item label="私网 IP">{a.private_ip ? <Text copyable>{str(a.private_ip)}</Text> : '-'}</Descriptions.Item>
            <Descriptions.Item label="创建时间" span={2}>{str(a.created_at)}</Descriptions.Item>
            <Descriptions.Item label="标签" span={2}>
              {Object.keys(tags).length === 0 ? '-' : Object.entries(tags).map(([k, v]) => (
                <Tag key={k}>{k}: {v}</Tag>
              ))}
            </Descriptions.Item>
          </Descriptions>
        </Card>
        <AliyunMonitorCard tenantId={tenantId} instanceId={String(a.id)} />
      </div>
    );
  }

  if (!detail) {
    return (
      <Card>
        <Empty description="实例详情加载失败">
          <Button onClick={() => navigate('/instances')}>返回实例列表</Button>
        </Empty>
      </Card>
    );
  }

  const powerItems = [
    { key: 'start', label: '启动', icon: <PlayCircleOutlined />, onClick: () => doPower('start') },
    { key: 'stop', label: '停止', icon: <PauseCircleOutlined />, onClick: () => doPower('stop') },
    { key: 'reboot', label: '重启', icon: <ReloadOutlined />, onClick: () => doPower('reboot') },
  ];

  const moreItems = [
    { key: 'rename', label: '改名', onClick: () => {
      Modal.confirm({
        title: '修改实例显示名',
        content: <Input id="rename-input" defaultValue={detail.name} />,
        onOk: async () => {
          const v = (document.getElementById('rename-input') as HTMLInputElement)?.value?.trim();
          if (v) { await renameInstance(tenantId, id, v); message.success('已改名'); loadDetail(); }
        },
      });
    } },
    { key: 'image', label: '创建定制映像', onClick: () => setImgModal(true) },
    { key: 'move', label: '移动资源（换 compartment）', onClick: async () => {
      setMoveModal(true);
      try {
        const cs = await getCompartments(tenantId);
        setCompartments(cs.map((c: { id: string; name: string }) => ({ value: c.id, label: c.name })));
      } catch { /* ignore */ }
    } },
    { key: 'diag-reboot', label: '发送诊断重启', danger: true, onClick: () => {
      Modal.confirm({
        title: '发送诊断重启？', content: '将触发实例的诊断重启，用于内核级故障排查。',
        okType: 'danger', onOk: async () => { await diagnosticAction(tenantId, id, 'DIAGNOSTICREBOOT'); message.success('诊断重启已发送'); },
      });
    } },
    { key: 'diag-interrupt', label: '发送诊断中断', danger: true, onClick: () => {
      Modal.confirm({
        title: '发送诊断中断？',
        content: '会导致操作系统崩溃并重启，可能造成数据损坏，仅用于高级故障排查。',
        okType: 'danger', onOk: async () => { await diagnosticAction(tenantId, id, 'SENDDIAGNOSTICINTERRUPT'); message.success('诊断中断已发送'); },
      });
    } },
    { key: 'run-cmd', label: '在实例上运行命令', onClick: () => setCmdModal(true) },
  ];

  return (
    <div>
      {/* 页头：对标 Console 的实例标题栏 */}
      <Card style={{ marginBottom: 16 }}>
        <Row justify="space-between" align="middle">
          <Col>
            <Space>
              <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/instances')} />
              <div>
                <Space>
                  <Text strong style={{ fontSize: 20 }}>{detail.name}</Text>
                  <Tag color={STATUS_COLOR[detail.status]}>{STATUS_TEXT[detail.status]}</Tag>
                </Space>
                <div><Text type="secondary" style={{ fontSize: 12 }}>实例详细信息 · {detail.region}</Text></div>
              </div>
            </Space>
          </Col>
          <Col>
            <Space>
              <Dropdown menu={{ items: powerItems }} disabled={opLoading}>
                <Button>电源操作 <DownOutlined /></Button>
              </Dropdown>
              <Dropdown menu={{ items: moreItems }} disabled={opLoading}>
                <Button>更多操作 <DownOutlined /></Button>
              </Dropdown>
              <Popconfirm title="确定终止该实例吗？此操作不可恢复！" description="引导卷将保留，可用于救援数据。" onConfirm={doTerminate}>
                <Button danger loading={opLoading}>终止</Button>
              </Popconfirm>
            </Space>
          </Col>
        </Row>
      </Card>

      <Card>
        <Tabs
          activeKey={tab}
          onChange={setTab}
          items={[
            { key: 'detail', label: '详细信息', children: <DetailTab detail={detail} extra={extra} loading={!!tabLoading.detail} /> },
            { key: 'network', label: '网络', children: <NetworkTabView detail={detail} data={network} loading={!!tabLoading.network} tenantId={tenantId} instanceId={id} onIpv6Attached={loadDetail} /> },
            { key: 'storage', label: '存储', children: <StorageTabView data={storage} loading={!!tabLoading.storage} /> },
            { key: 'security', label: '安全', children: <SecurityTabView detail={detail} data={security} loading={!!tabLoading.security} /> },
            { key: 'management', label: '管理', children: <MgmtTabView mgmt={mgmt} plugins={plugins} loading={!!tabLoading.management} /> },
            { key: 'osmgmt', label: '操作系统管理', children: (
              <OsMgmtTabView
                tenantId={tenantId} instanceId={id}
                histId={histId} setHistId={setHistId}
                histContent={histContent} setHistContent={setHistContent}
                histLoading={histLoading} setHistLoading={setHistLoading}
              />
            ) },
            { key: 'monitor', label: '监视', children: <MonitorTabView charts={metrics} loading={!!tabLoading.monitor} /> },
            { key: 'work', label: '工作请求', children: <WorkTabView data={workReqs} loading={!!tabLoading.work} /> },
            { key: 'tags', label: '标记', children: <TagsTabView detail={detail} /> },
          ]}
        />
      </Card>

      <SerialConsole tenantId={tenantId} instanceId={id} instanceName={detail.name} />

      {/* 创建定制映像 */}
      <Modal title="创建定制映像" open={imgModal} onCancel={() => setImgModal(false)} onOk={() => form.submit()} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={async (v) => {
          await createCustomImage(tenantId, id, v.display_name);
          message.success('定制映像创建已提交');
          setImgModal(false);
        }}>
          <Form.Item name="display_name" label="映像名称" rules={[{ required: true }]} initialValue={`${detail.name}-image`}>
            <Input />
          </Form.Item>
          <Alert type="warning" showIcon message="实例需要处于关机状态，创建过程需要几分钟" />
        </Form>
      </Modal>

      {/* 移动资源 */}
      <Modal title="移动资源" open={moveModal} onCancel={() => setMoveModal(false)} onOk={() => form.submit()} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={async (v) => {
          await changeInstanceCompartment(tenantId, id, v.compartment_id);
          message.success('移动请求已提交');
          setMoveModal(false);
        }}>
          <Form.Item name="compartment_id" label="目标 Compartment" rules={[{ required: true }]}>
            <Select options={compartments} showSearch optionFilterProp="label" placeholder="选择目标 compartment" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 运行命令 */}
      <Modal title="在实例上运行命令" open={cmdModal} onCancel={() => setCmdModal(false)} onOk={() => form.submit()} destroyOnClose width={640}>
        <Form form={form} layout="vertical" onFinish={async (v) => {
          const r = await runInstanceCommand(tenantId, id, v.content, v.display_name);
          message.success(`命令已下发：${r.id}`);
          setCmdModal(false);
        }}>
          <Alert type="info" showIcon style={{ marginBottom: 12 }} message="需要实例安装 Cloud Agent 并启用 Run Command 插件，命令以 root 身份执行" />
          <Form.Item name="display_name" label="命令名称（可选）">
            <Input placeholder="默认自动生成" />
          </Form.Item>
          <Form.Item name="content" label="Shell 脚本" rules={[{ required: true, message: '请输入脚本内容' }]}>
            <Input.TextArea rows={6} placeholder="#!/bin/bash&#10;df -h" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

/* ================= 详细信息 Tab ================= */
function DetailTab({ detail, extra, loading }: { detail: Detail; extra: DetailExtra | null; loading: boolean }) {
  return (
    <div>
      <Divider orientation="left" style={{ marginTop: 0 }}>一般信息</Divider>
      <Descriptions column={2} bordered size="small">
        <Descriptions.Item label="可用域">{detail.availabilityDomainFull || detail.ad}</Descriptions.Item>
        <Descriptions.Item label="容错域">{detail.faultDomain || '-'}</Descriptions.Item>
        <Descriptions.Item label="区域">{detail.region}</Descriptions.Item>
        <Descriptions.Item label="区间（Compartment）" span={2}>
          <Space>
            {detail.compartmentName ? <Tag color="blue">{detail.compartmentName}</Tag> : null}
            <Text copyable ellipsis style={{ maxWidth: 420 }}>{detail.compartmentId}</Text>
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="OCID" span={2}>
          <Text copyable ellipsis style={{ maxWidth: 600 }}>{detail.ocid}</Text>
        </Descriptions.Item>
        <Descriptions.Item label="容量类型">{extra?.capacity_type || '-'}</Descriptions.Item>
        <Descriptions.Item label="启动时间">{fmtTime(extra?.time_created)}</Descriptions.Item>
      </Descriptions>

      <Divider orientation="left">实例访问权限</Divider>
      <Descriptions column={2} bordered size="small">
        <Descriptions.Item label="公网 IP 地址">
          {detail.vnic?.publicIp || detail.publicIp ? <Text copyable>{detail.vnic?.publicIp || detail.publicIp}</Text> : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="用户名">{extra?.ssh_username ? <Text code>{extra.ssh_username}</Text> : '-'}</Descriptions.Item>
      </Descriptions>

      <Divider orientation="left">映像详细信息</Divider>
      {loading && !extra ? <Skeleton active paragraph={{ rows: 3 }} /> : (
        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label="操作系统">{extra?.image?.operating_system || '-'}</Descriptions.Item>
          <Descriptions.Item label="版本">{extra?.image?.operating_system_version || '-'}</Descriptions.Item>
          <Descriptions.Item label="映像" span={2}>
            <Text copyable ellipsis style={{ maxWidth: 600 }}>{extra?.image?.display_name || detail.imageId}</Text>
          </Descriptions.Item>
        </Descriptions>
      )}

      <Divider orientation="left">配置规格配置</Divider>
      <Descriptions column={2} bordered size="small">
        <Descriptions.Item label="配置">{detail.shape}</Descriptions.Item>
        <Descriptions.Item label="OCPU 计数">{detail.ocpus || '-'}</Descriptions.Item>
        <Descriptions.Item label="内存 (GB)">{detail.memoryGb ? `${detail.memoryGb}` : '-'}</Descriptions.Item>
        <Descriptions.Item label="网络带宽 (Gbps)">
          {detail.networkBandwidthGbps != null ? <Tag color="blue">{detail.networkBandwidthGbps} Gbps</Tag> : '未查询到'}
        </Descriptions.Item>
      </Descriptions>

      <Divider orientation="left">启动选项</Divider>
      {loading && !extra ? <Skeleton active paragraph={{ rows: 4 }} /> : extra?.launch_options ? (
        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label="NIC 附加类型">{extra.launch_options.network_type || '-'}</Descriptions.Item>
          <Descriptions.Item label="远程数据卷">{extra.launch_options.remote_data_volume_type || '-'}</Descriptions.Item>
          <Descriptions.Item label="固件">{extra.launch_options.firmware || '-'}</Descriptions.Item>
          <Descriptions.Item label="引导卷类型">{extra.launch_options.boot_volume_type || '-'}</Descriptions.Item>
          <Descriptions.Item label="传输中加密">{boolTag(extra.launch_options.is_pv_encryption_in_transit_enabled)}</Descriptions.Item>
          <Descriptions.Item label="安全引导">{boolTag(extra.launch_options.is_secure_boot_enabled)}</Descriptions.Item>
          <Descriptions.Item label="测量引导">{boolTag(extra.launch_options.is_measured_boot_enabled)}</Descriptions.Item>
          <Descriptions.Item label="可信平台模块">{boolTag(extra.launch_options.is_trusted_platform_module_enabled)}</Descriptions.Item>
        </Descriptions>
      ) : <Empty description="无启动选项数据" />}
    </div>
  );
}

/* ================= 网络 Tab ================= */
function NetworkTabView({ detail, data, loading, tenantId, instanceId, onIpv6Attached }: {
  detail: Detail; data: NetworkTab | null; loading: boolean;
  tenantId: number; instanceId: string; onIpv6Attached: () => void;
}) {
  const v = detail.vnic;
  const [ipv6Loading, setIpv6Loading] = useState(false);
  const [boostTask, setBoostTask] = useState<BoostTask | null>(null);
  const [boostLoading, setBoostLoading] = useState(false);

  const doAttachIpv6 = async () => {
    setIpv6Loading(true);
    try {
      const r = await attachIpv6(tenantId, instanceId);
      message.success(`IPv6 附加成功：${r.ip_address}`);
      onIpv6Attached();
    } finally {
      setIpv6Loading(false);
    }
  };

  const doBoost = async (action: 'enable' | 'disable') => {
    setBoostLoading(true);
    try {
      const { task_id } = action === 'enable'
        ? await enable500M(tenantId, instanceId)
        : await disable500M(tenantId, instanceId);
      message.info('任务已下发，后台执行中（约需 2-5 分钟）');
      const poll = async () => {
        try {
          const t = await getBoostTask(task_id);
          setBoostTask(t);
          if (t.status === 'running') {
            setTimeout(poll, 8000);
          } else if (t.status === 'success') {
            message.success(t.message);
          } else {
            message.error(t.message);
          }
        } catch { /* 忽略轮询异常 */ }
      };
      poll();
    } finally {
      setBoostLoading(false);
    }
  };
  return (
    <div>
      <Divider orientation="left" style={{ marginTop: 0 }}>主要 VNIC</Divider>
      <Descriptions column={2} bordered size="small">
        <Descriptions.Item label="公共 IPv4 地址">{v?.publicIp ? <Text copyable>{v.publicIp}</Text> : '-'}</Descriptions.Item>
        <Descriptions.Item label="专用 IPv4 地址">{v?.privateIp ? <Text copyable>{v.privateIp}</Text> : '-'}</Descriptions.Item>
        <Descriptions.Item label="IPv6" span={2}>
          <Space wrap>
            {(v?.ipv6Addresses ?? []).map((ip) => <Text key={ip} copyable code style={{ fontSize: 12 }}>{ip}</Text>)}
            <Button size="small" type="dashed" loading={ipv6Loading} onClick={doAttachIpv6}>
              附加 IPv6
            </Button>
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="路由表">{data?.route_table_name || (loading ? <Skeleton.Input active size="small" /> : '-')}</Descriptions.Item>
        <Descriptions.Item label="网络安全组（NSG）">
          {(v?.nsgs?.length ?? 0) > 0 ? v!.nsgs.map((g) => <Tag key={g.id} color="purple">{g.name || g.id.slice(-12)}</Tag>) : <Text type="secondary">未关联 NSG</Text>}
        </Descriptions.Item>
        <Descriptions.Item label="子网" span={2}>{v?.subnetName || v?.subnetId || '-'}</Descriptions.Item>
        <Descriptions.Item label="MAC">{v?.mac || '-'}</Descriptions.Item>
        <Descriptions.Item label="主机名">{v?.hostname || '-'}</Descriptions.Item>
        <Descriptions.Item label="内部 FQDN" span={2}>
          {data?.internal_fqdn ? <Text copyable>{data.internal_fqdn}</Text> : (loading ? <Skeleton.Input active size="small" /> : '-')}
        </Descriptions.Item>
      </Descriptions>

      <Divider orientation="left">附加的 VNIC</Divider>
      {loading && !data ? <Skeleton active paragraph={{ rows: 3 }} /> : (
        <Table
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={data?.vnic_attachments ?? []}
          columns={[
            { title: '名称', dataIndex: 'display_name', key: 'display_name', render: (x: string) => x || '-' },
            { title: '状态', dataIndex: 'lifecycle_state', key: 'lifecycle_state', render: (x: string) => <Tag>{x}</Tag> },
            { title: '网卡序号', dataIndex: 'nic_index', key: 'nic_index' },
            { title: '创建时间', dataIndex: 'time_created', key: 'time_created', render: fmtTime },
          ]}
          locale={{ emptyText: '无附加 VNIC' }}
        />
      )}

      <Divider orientation="left">下行加速（一键 500M）</Divider>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          仅支持 AMD 机型：通过网络负载均衡器实现约 500Mbps 下行，任务后台执行约需 2-5 分钟。
        </Text>
        <Space wrap>
          <Button type="primary" size="small" loading={boostLoading} onClick={() => doBoost('enable')}>
            一键开启 500M
          </Button>
          <Popconfirm
            title="关闭下行 500M？"
            description="将删除 NLB / NAT 网关及相关路由表，实例恢复直连。"
            onConfirm={() => doBoost('disable')}
          >
            <Button size="small" danger loading={boostLoading}>
              关闭 500M
            </Button>
          </Popconfirm>
        </Space>
        {boostTask && (
          <Alert
            type={boostTask.status === 'failed' ? 'error' : boostTask.status === 'success' ? 'success' : 'info'}
            showIcon
            message={boostTask.status === 'running' ? '任务执行中…' : boostTask.status === 'success' ? '任务成功' : '任务失败'}
            description={boostTask.message}
          />
        )}
      </Space>
    </div>
  );
}

/* ================= 存储 Tab ================= */
function StorageTabView({ data, loading }: { data: StorageTab | null; loading: boolean }) {
  if (loading && !data) return <Skeleton active paragraph={{ rows: 6 }} />;
  const bv = data?.boot_volume;
  const cols: ColumnsType<DataVolumeExt> = [
    { title: '名称', dataIndex: 'display_name', key: 'display_name', render: (x: string) => x || '-' },
    { title: '状态', dataIndex: 'lifecycle_state', key: 'lifecycle_state', render: (x: string) => <Tag>{x}</Tag> },
    { title: '大小', dataIndex: 'size_in_gbs', key: 'size_in_gbs', render: (x: number) => x != null ? `${x} GB` : '-' },
    { title: '卷类型', dataIndex: 'volume_type', key: 'volume_type' },
    { title: 'VPU/GB', dataIndex: 'vpus_per_gb', key: 'vpus_per_gb' },
    { title: '设备路径', dataIndex: 'device', key: 'device' },
    { title: '已附加', dataIndex: 'attached_time', key: 'attached_time', render: fmtTime },
  ];
  return (
    <div>
      <Divider orientation="left" style={{ marginTop: 0 }}>引导卷</Divider>
      {bv ? (
        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label="引导卷名称" span={2}><Text copyable>{bv.display_name}</Text></Descriptions.Item>
          <Descriptions.Item label="状态"><Tag>{bv.lifecycle_state}</Tag></Descriptions.Item>
          <Descriptions.Item label="大小">{bv.size_in_gbs} GB</Descriptions.Item>
          <Descriptions.Item label="传输中加密">{boolTag(bv.is_transit_encryption_enabled)}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{fmtTime(bv.time_created)}</Descriptions.Item>
          <Descriptions.Item label="已附加">{fmtTime(bv.attached_time)}</Descriptions.Item>
          <Descriptions.Item label="映像" span={2}>
            <Text ellipsis style={{ maxWidth: 600 }} title={bv.source_image}>{bv.source_image || '-'}</Text>
          </Descriptions.Item>
        </Descriptions>
      ) : <Empty description="无引导卷数据" />}

      <Divider orientation="left">附加的块存储卷</Divider>
      <Table size="small" rowKey="id" pagination={false} dataSource={data?.data_volumes ?? []} columns={cols} locale={{ emptyText: '无附加数据卷' }} />
    </div>
  );
}

/* ================= 安全 Tab ================= */
function SecurityTabView({ detail, data, loading }: { detail: Detail; data: SecurityTab | null; loading: boolean }) {
  if (loading && !data) return <Skeleton active paragraph={{ rows: 6 }} />;
  const protoName = (p: string) => p === '6' ? 'TCP' : p === '17' ? 'UDP' : p === '1' ? 'ICMP' : p === 'all' ? '全部' : p || '-';
  return (
    <div>
      <Divider orientation="left" style={{ marginTop: 0 }}>网络安全组（NSG）</Divider>
      {(detail.vnic?.nsgs?.length ?? 0) > 0 ? (
        <Space wrap>{detail.vnic!.nsgs.map((g) => <Tag key={g.id} color="purple">{g.name || g.id.slice(-12)}</Tag>)}</Space>
      ) : <Text type="secondary">未关联 NSG</Text>}
      <Divider orientation="left">子网安全列表规则</Divider>
      {(data?.security_list_rules ?? []).length === 0 ? <Empty description="无安全列表数据" /> : (
        data!.security_list_rules.map((sl) => (
          <Card key={sl.id} size="small" title={sl.name} style={{ marginBottom: 12 }}>
            <Table
              size="small" rowKey={(r, i) => `${r.direction}-${i}`} pagination={false}
              dataSource={sl.rules}
              columns={[
                { title: '方向', dataIndex: 'direction', key: 'direction', width: 80, render: (x: string) => <Tag color={x === '入站' ? 'green' : 'blue'}>{x}</Tag> },
                { title: '协议', dataIndex: 'protocol', key: 'protocol', width: 100, render: protoName },
                { title: '源 / 目标', dataIndex: 'source', key: 'source' },
                { title: '类型', dataIndex: 'source_type', key: 'source_type', width: 120 },
                { title: '描述', dataIndex: 'description', key: 'description' },
              ]}
            />
          </Card>
        ))
      )}
    </div>
  );
}

/* ================= 管理 Tab ================= */
function MgmtTabView({ mgmt, plugins, loading }: { mgmt: ManagementTab | null; plugins: AgentPlugins | null; loading: boolean }) {
  if (loading && !mgmt) return <Skeleton active paragraph={{ rows: 6 }} />;
  return (
    <div>
      <Divider orientation="left" style={{ marginTop: 0 }}>维护事件</Divider>
      <Table
        size="small" rowKey="id" pagination={false}
        dataSource={mgmt?.maintenance_events ?? []}
        columns={[
          { title: '名称', dataIndex: 'display_name', key: 'display_name' },
          { title: '类别', dataIndex: 'maintenance_category', key: 'maintenance_category' },
          { title: '状态', dataIndex: 'lifecycle_state', key: 'lifecycle_state', render: (x: string) => <Tag>{x}</Tag> },
          { title: '开始时间', dataIndex: 'time_started', key: 'time_started', render: fmtTime },
          { title: '结束时间', dataIndex: 'time_finished', key: 'time_finished', render: fmtTime },
        ]}
        locale={{ emptyText: '没有可显示的项' }}
      />
      <Divider orientation="left">Oracle Cloud Agent 插件</Divider>
      {!plugins?.available ? (
        <Alert type="info" showIcon message={plugins?.note || '未找到 Cloud Agent'} />
      ) : (
        <Table
          size="small" rowKey="name" pagination={false}
          dataSource={plugins.plugins}
          columns={[
            { title: '插件名称', dataIndex: 'name', key: 'name' },
            { title: '状态', dataIndex: 'status', key: 'status', render: (x: string) => <Tag color={x === 'RUNNING' ? 'green' : undefined}>{x}</Tag> },
            { title: '上次更新', dataIndex: 'time_last_updated', key: 'time_last_updated', render: fmtTime },
          ]}
        />
      )}
    </div>
  );
}

/* ================= 操作系统管理 Tab ================= */
function OsMgmtTabView({ tenantId, instanceId, histId, setHistId, histContent, setHistContent, histLoading, setHistLoading }: {
  tenantId: number; instanceId: string;
  histId: string; setHistId: (v: string) => void;
  histContent: string; setHistContent: (v: string) => void;
  histLoading: boolean; setHistLoading: (v: boolean) => void;
}) {
  const doCapture = async () => {
    setHistLoading(true);
    try {
      const r = await captureConsoleHistory(tenantId, instanceId);
      setHistId(r.id);
      message.success('控制台历史截取已提交，稍等 10 秒后查看内容');
    } finally {
      setHistLoading(false);
    }
  };
  const doView = async () => {
    if (!histId) { message.warning('请先截取控制台历史'); return; }
    setHistLoading(true);
    try {
      const r = await getConsoleHistoryContent(tenantId, instanceId, histId);
      setHistContent(r.content || '(空)');
    } finally {
      setHistLoading(false);
    }
  };
  return (
    <div>
      <Divider orientation="left" style={{ marginTop: 0 }}>控制台连接</Divider>
      <Paragraph type="secondary">可使用控制台连接对运行不正常的实例进行故障排除。</Paragraph>
      <Space>
        <SerialConsole tenantId={tenantId} instanceId={instanceId} instanceName="" />
      </Space>
      <Divider orientation="left">控制台历史记录</Divider>
      <Paragraph type="secondary">控制台历史记录显示串行控制台捕获的操作系统级别错误消息，可用于检查实例状态或问题诊断。</Paragraph>
      <Space style={{ marginBottom: 12 }}>
        <Button onClick={doCapture} loading={histLoading}>截取当前历史记录</Button>
        <Button onClick={doView} loading={histLoading} disabled={!histId}>查看内容</Button>
        {histId && <Text type="secondary" style={{ fontSize: 12 }}>{histId.slice(-12)}</Text>}
      </Space>
      {histContent && (
        <div style={{ background: '#0d1117', color: '#c9d1d9', borderRadius: 6, padding: '8px 12px', fontSize: 12, fontFamily: 'Menlo, Consolas, monospace', whiteSpace: 'pre-wrap', maxHeight: 400, overflowY: 'auto' }}>
          {histContent}
        </div>
      )}
    </div>
  );
}

/* ================= 监视 Tab ================= */
/** 阿里云实例监控卡片（CMS 指标） */
function AliyunMonitorCard({ tenantId, instanceId }: { tenantId: number; instanceId: string }) {
  const [charts, setCharts] = useState<{ metric: string; title: string; points: { time: string; value: number }[]; error?: string }[] | null>(null);
  const [hours, setHours] = useState(6);

  useEffect(() => {
    let cancelled = false;
    setCharts(null);
    getAliInstanceMetrics(tenantId, instanceId, hours)
      .then((cs) => { if (!cancelled) setCharts(cs); })
      .catch(() => { if (!cancelled) setCharts([]); });
    return () => { cancelled = true; };
  }, [tenantId, instanceId, hours]);

  const hasData = (charts ?? []).some((c) => c.points.length > 0);
  return (
    <Card
      title="监控指标"
      style={{ marginTop: 16 }}
      extra={
        <Select
          size="small" value={hours} style={{ width: 120 }}
          onChange={setHours}
          options={[
            { value: 6, label: '近 6 小时' },
            { value: 24, label: '近 24 小时' },
            { value: 72, label: '近 3 天' },
          ]}
        />
      }
    >
      {charts === null ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : !hasData ? (
        <Empty description="暂无监控数据（实例可能未运行或 CMS 暂无数据）" />
      ) : (
        <Row gutter={[16, 16]}>
          {charts.map((c) => (
            <Col xs={24} lg={12} key={c.metric}>
              <Card size="small" title={c.title}>
                {c.points.length > 0 ? (
                  <Chart
                    height={220}
                    option={{
                      tooltip: { trigger: 'axis' },
                      xAxis: { type: 'category', data: c.points.map((p) => (p.time || '').slice(5, 16)) },
                      yAxis: { type: 'value' },
                      series: [{ type: 'line', smooth: true, showSymbol: false, data: c.points.map((p) => p.value), areaStyle: { opacity: 0.15 } }],
                      grid: { left: 48, right: 16, top: 24, bottom: 28 },
                    }}
                  />
                ) : (
                  <Empty description={c.error ? '查询失败' : '暂无数据'} style={{ padding: '24px 0' }} />
                )}
              </Card>
            </Col>
          ))}
        </Row>
      )}
    </Card>
  );
}

function MonitorTabView({ charts, loading }: { charts: MetricChart[] | null; loading: boolean }) {  if (loading && !charts) return <Skeleton active paragraph={{ rows: 8 }} />;
  const hasData = (charts ?? []).some((c) => c.points.length > 0);
  return (
    <div>
      {!hasData && (
        <Alert type="info" showIcon style={{ marginBottom: 16 }} message="实例未安装 Cloud Agent 或插件未启用，无法获取 CPU/内存等系统指标" />
      )}
      <Row gutter={[16, 16]}>
        {(charts ?? []).map((c) => (
          <Col xs={24} lg={12} key={c.metric}>
            <Card size="small" title={c.title}>
              {c.points.length > 0 ? (
                <Chart
                  height={220}
                  option={{
                    tooltip: { trigger: 'axis' },
                    xAxis: { type: 'category', data: c.points.map((p) => (p.time || '').slice(5, 16)) },
                    yAxis: { type: 'value' },
                    series: [{ type: 'line', smooth: true, showSymbol: false, data: c.points.map((p) => p.value), areaStyle: { opacity: 0.15 } }],
                    grid: { left: 48, right: 16, top: 24, bottom: 28 },
                  }}
                />
              ) : (
                <Empty description={c.error ? `查询失败` : '暂无数据'} style={{ padding: '24px 0' }} />
              )}
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}

/* ================= 工作请求 Tab ================= */
function WorkTabView({ data, loading }: { data: WorkRequests | null; loading: boolean }) {
  if (loading && !data) return <Skeleton active paragraph={{ rows: 6 }} />;
  return (
    <Table
      size="small" rowKey="id" pagination={false}
      dataSource={data?.work_requests ?? []}
      columns={[
        { title: '操作类型', dataIndex: 'operation_type', key: 'operation_type' },
        { title: '状态', dataIndex: 'status', key: 'status', render: (x: string) => <Tag color={x === 'SUCCEEDED' ? 'green' : x === 'FAILED' ? 'red' : 'blue'}>{x}</Tag> },
        { title: '进度', dataIndex: 'percent_complete', key: 'percent_complete', render: (x: number | null) => x != null ? `${x}%` : '-' },
        { title: '开始时间', dataIndex: 'time_accepted', key: 'time_accepted', render: fmtTime },
        { title: '结束时间', dataIndex: 'time_finished', key: 'time_finished', render: fmtTime },
      ]}
      locale={{ emptyText: '没有可显示的项' }}
    />
  );
}

/* ================= 标记 Tab ================= */
function TagsTabView({ detail }: { detail: Detail }) {
  const defined = detail.definedTags ?? {};
  const freeform = detail.freeformTags ?? {};
  const definedRows: { ns: string; key: string; value: string }[] = [];
  Object.entries(defined).forEach(([ns, kv]) => {
    Object.entries(kv as Record<string, unknown>).forEach(([k, v]) => {
      definedRows.push({ ns, key: k, value: String(v) });
    });
  });
  return (
    <div>
      <Paragraph type="secondary">添加其他元数据以使用自由形式和定义的标记组织资源。</Paragraph>
      <Divider orientation="left" style={{ marginTop: 0 }}>定义的标记</Divider>
      <Table
        size="small" rowKey={(r) => `${r.ns}:${r.key}`} pagination={false}
        dataSource={definedRows}
        columns={[
          { title: '名称空间', dataIndex: 'ns', key: 'ns' },
          { title: '标记键', dataIndex: 'key', key: 'key' },
          { title: '标记值', dataIndex: 'value', key: 'value' },
          { title: '类型', key: 'type', render: () => '已定义' },
        ]}
        locale={{ emptyText: '无定义的标记' }}
      />
      <Divider orientation="left">自由形式标记</Divider>
      <Table
        size="small" rowKey="key" pagination={false}
        dataSource={Object.entries(freeform).map(([k, v]) => ({ key: k, value: v }))}
        columns={[
          { title: '标记键', dataIndex: 'key', key: 'key' },
          { title: '标记值', dataIndex: 'value', key: 'value' },
        ]}
        locale={{ emptyText: '无自由形式标记' }}
      />
    </div>
  );
}
