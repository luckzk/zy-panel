import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Row,
  Select,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { listTenants, type TenantOption } from '../api/tenants';
import { listInstances } from '../api/instances';
import AliyunEips from '../components/AliyunEips';
import { getIpMap, refreshIpMap, type IpMapPoint } from '../api/ipinfo';
import type { Instance } from '../types';
import {
  cancelChangeIpTask,
  createChangeIpTask,
  listChangeIpTasks,
  type ChangeIpCreate,
  type IpTask,
} from '../api/network';

const { Text } = Typography;
const { TextArea } = Input;

const STATUS_META: Record<IpTask['status'], { color: string; text: string }> = {
  pending: { color: 'default', text: '等待中' },
  running: { color: 'processing', text: '进行中' },
  success: { color: 'success', text: '成功' },
  failed: { color: 'error', text: '失败' },
};

interface ChangeIpForm {
  tenant_id: number;
  instance_id: string;
  cidrs_text: string;
  update_dns: boolean;
  max_retries: number;
}

/** IP 总览：所有租户实例公网 IP + 归属地 */
function IpOverview() {
  const [data, setData] = useState<IpMapPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const fetch = useCallback(async (force = false) => {
    setLoading(true);
    try {
      setData(force ? await refreshIpMap() : await getIpMap());
    } catch {
      setData([]);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { fetch(); }, [fetch]);
  const columns: ColumnsType<IpMapPoint> = [
    {
      title: '公网 IP', dataIndex: 'ip', key: 'ip',
      render: (v: string) => <Text copyable code>{v}</Text>,
    },
    {
      title: '归属地', key: 'location',
      render: (_, r) => [r.country, r.city].filter(Boolean).join(' · ') || <Text type="secondary">—</Text>,
    },
    { title: '运营商', dataIndex: 'isp', key: 'isp', render: (v: string | null) => v || <Text type="secondary">—</Text> },
    { title: '实例', dataIndex: 'instance_name', key: 'instance_name' },
    { title: '租户', dataIndex: 'tenant_name', key: 'tenant_name' },
  ];
  return (
    <Card
      title="公网 IP 总览"
      extra={
        <Button onClick={() => fetch(true)} loading={loading}>
          刷新归属地
        </Button>
      }
    >
      <Table<IpMapPoint>
        rowKey="ip"
        columns={columns}
        dataSource={data}
        loading={loading}
        pagination={{ showSizeChanger: true, showTotal: (t) => `共 ${t} 个 IP` }}
        locale={{ emptyText: '暂无公网 IP（实例列表为空或均未分配公网 IP）' }}
      />
    </Card>
  );
}

/** IP 管理页：IP 总览 / 更换 IP（OCI）/ EIP 管理（阿里云） */
export default function Network() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [instances, setInstances] = useState<Instance[]>([]);
  const [instancesLoading, setInstancesLoading] = useState(false);
  const [tasks, setTasks] = useState<IpTask[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<ChangeIpForm>();
  const tenantId = Form.useWatch('tenant_id', form);
  const instanceId = Form.useWatch('instance_id', form);

  const tenantName = useCallback(
    (id: number) => tenants.find((t) => t.id === id)?.name ?? `#${id}`,
    [tenants],
  );

  /** 任务列表 */
  const fetchTasks = useCallback(async () => {
    setTasksLoading(true);
    try {
      setTasks(await listChangeIpTasks());
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      setTasksLoading(false);
    }
  }, []);

  /** 租户变化时拉取该租户实例 */
  const fetchInstances = useCallback(async (tid: number | undefined) => {
    if (!tid) {
      setInstances([]);
      return;
    }
    setInstancesLoading(true);
    try {
      const t = (await listTenants()).find((x) => x.id === tid);
      const { items } = await listInstances({ tenant_id: tid, page_size: 200 }, t?.name ?? '');
      setInstances(items);
    } catch {
      setInstances([]);
    } finally {
      setInstancesLoading(false);
    }
  }, []);

  useEffect(() => {
    listTenants().then(setTenants).catch(() => setTenants([]));
    fetchTasks();
  }, [fetchTasks]);

  useEffect(() => {
    form.setFieldsValue({ instance_id: undefined });
    fetchInstances(tenantId);
  }, [tenantId, form, fetchInstances]);

  /** 有进行中任务时每 10 秒轮询刷新 */
  const hasActive = useMemo(
    () => tasks.some((t) => t.status === 'pending' || t.status === 'running'),
    [tasks],
  );
  useEffect(() => {
    if (!hasActive) return;
    const timer = setInterval(fetchTasks, 10000);
    return () => clearInterval(timer);
  }, [hasActive, fetchTasks]);

  const currentInstance = useMemo(
    () => instances.find((i) => i.id === instanceId),
    [instances, instanceId],
  );

  const onFinish = async (values: ChangeIpForm) => {
    const cidrs = (values.cidrs_text || '')
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);
    const body: ChangeIpCreate = {
      tenant_id: values.tenant_id,
      instance_id: values.instance_id,
      preferred_cidrs: cidrs,
      update_dns: values.update_dns ?? false,
      max_retries: values.max_retries ?? 3,
    };
    setSubmitting(true);
    try {
      await createChangeIpTask(body);
      message.success('换 IP 任务已发起，后台 worker 正在执行');
      form.resetFields();
      fetchTasks();
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      setSubmitting(false);
    }
  };

  const onCancel = async (id: number) => {
    try {
      await cancelChangeIpTask(id);
      message.success('任务已取消');
      fetchTasks();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const columns: ColumnsType<IpTask> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 70 },
    {
      title: '租户',
      dataIndex: 'tenant_id',
      key: 'tenant_id',
      width: 120,
      render: (v: number) => tenantName(v),
    },
    {
      title: '实例',
      dataIndex: 'instance_id',
      key: 'instance_id',
      width: 200,
      ellipsis: true,
      render: (v: string) => (
        <Tooltip title={v}>
          <Text code style={{ fontSize: 12 }}>
            {v.length > 28 ? `${v.slice(0, 28)}…` : v}
          </Text>
        </Tooltip>
      ),
    },
    {
      title: 'IP 变化',
      key: 'ip',
      width: 260,
      render: (_, r) => (
        <Text>
          {r.old_ip ?? '-'} <Text type="secondary">→</Text>{' '}
          <Text strong type={r.status === 'success' ? 'success' : undefined}>
            {r.new_ip ?? '-'}
          </Text>
        </Text>
      ),
    },
    {
      title: '尝试',
      key: 'attempts',
      width: 90,
      render: (_, r) => `${r.attempts}/${r.max_retries}`,
    },
    {
      title: 'DNS 联动',
      key: 'dns',
      width: 110,
      render: (_, r) =>
        !r.update_dns ? (
          <Text type="secondary">不联动</Text>
        ) : r.dns_updated ? (
          <Tag color="success">已同步</Tag>
        ) : (
          <Tag color="default">待同步</Tag>
        ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v: IpTask['status']) => <Tag color={STATUS_META[v].color}>{STATUS_META[v].text}</Tag>,
    },
    {
      title: '错误信息',
      dataIndex: 'last_error',
      key: 'last_error',
      ellipsis: true,
      render: (v: string | null) =>
        v ? (
          <Tooltip title={v}>
            <Text type="danger">{v}</Text>
          </Tooltip>
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (v: string | null) =>
        v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      fixed: 'right',
      render: (_, r) =>
        r.status === 'pending' || r.status === 'running' ? (
          <Popconfirm title="确定取消该换 IP 任务吗？" onConfirm={() => onCancel(r.id)}>
            <Button type="link" size="small" danger>
              取消
            </Button>
          </Popconfirm>
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
  ];

  return (
    <Tabs
      defaultActiveKey="overview"
      items={[
        {
          key: 'overview',
          label: 'IP 总览',
          children: <IpOverview />,
        },
        {
          key: 'change',
          label: '更换 IP',
          children: (
            <div>
              <Card title="更换公网 IP" style={{ marginBottom: 16 }}>
        <Form<ChangeIpForm>
          form={form}
          layout="vertical"
          onFinish={onFinish}
          initialValues={{ update_dns: false, max_retries: 3 }}
          style={{ maxWidth: 720 }}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="tenant_id" label="租户" rules={[{ required: true, message: '请选择租户' }]}>
                <Select
                  placeholder="请选择租户"
                  options={tenants.map((t) => ({ label: `${t.name}（${t.region}）`, value: t.id }))}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="instance_id" label="选择实例" rules={[{ required: true, message: '请选择实例' }]}>
                <Select
                  placeholder={tenantId ? '请选择要换 IP 的实例' : '请先选择租户'}
                  loading={instancesLoading}
                  disabled={!tenantId}
                  options={instances.map((i) => ({
                    label: `${i.name}（${i.publicIp || '无公网 IP'}）`,
                    value: i.id,
                  }))}
                />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="当前公网 IP">
                <Input value={currentInstance?.publicIp || '-'} disabled />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="max_retries"
                label="最大重试次数"
                tooltip="偏好 CIDR 未命中时，删除重建新 IP 的最多次数（1~20）"
                rules={[{ required: true }]}
              >
                <InputNumber min={1} max={20} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="cidrs_text"
            label="CIDR 网段偏好"
            extra="每行一个网段（如 203.0.113.0/24），换到偏好网段的 IP 为止；留空则随机更换"
          >
            <TextArea rows={3} placeholder={'203.0.113.0/24\n198.51.100.0/24'} />
          </Form.Item>
          <Form.Item name="update_dns" label="换 IP 后自动更新 Cloudflare DNS" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={submitting}>
              开始更换
            </Button>
          </Form.Item>
        </Form>
        <Text type="secondary" style={{ fontSize: 12 }}>
          注意：过于频繁更换 IP 可能导致账号受限，请谨慎操作。后台 worker 每 30 秒轮询执行，有进行中任务时列表每 10 秒自动刷新。
        </Text>
      </Card>

      <Card
        title="换 IP 任务"
        extra={
          <Button onClick={fetchTasks} loading={tasksLoading}>
            刷新
          </Button>
        }
      >
        <Table<IpTask>
          rowKey="id"
          columns={columns}
          dataSource={tasks}
          loading={tasksLoading}
          scroll={{ x: 1500 }}
          pagination={{ showSizeChanger: true, showTotal: (t) => `共 ${t} 个任务` }}
        />
      </Card>
            </div>
          ),
        },
        {
          key: 'eip',
          label: 'EIP 管理',
          children: <AliyunEips />,
        },
      ]}
    />
  );
}
