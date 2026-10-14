import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Button,
  Card,
  Checkbox,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
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
import AliyunVolumes from '../components/AliyunVolumes';
import type { Instance } from '../types';
import {
  listBlockVolumes,
  listVolumes,
  rescueVolume,
  resizeVolume,
  unrescueVolume,
  type VolumeInfo,
} from '../api/volumes';

const { Text } = Typography;

/** localStorage：已救援的卷（后端无状态，本地记录） */
const RESCUED_KEY = 'oci-panel:rescued-volumes';
function loadRescued(): Record<string, string[]> {
  try {
    return JSON.parse(localStorage.getItem(RESCUED_KEY) || '{}');
  } catch {
    return {};
  }
}

interface RescueFormValues {
  instanceId: string;
  confirmed: boolean;
}

/** 卷管理页：引导卷 / 数据卷 Tab + 扩容 + 救援（仅引导卷） */
export default function Volumes() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number>();
  const [compartmentId, setCompartmentId] = useState('');
  const [tab, setTab] = useState<'boot' | 'block'>('boot');
  const [list, setList] = useState<VolumeInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [tenantsLoaded, setTenantsLoaded] = useState(false);
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<VolumeInfo | null>(null);
  const [form] = Form.useForm<{ sizeGb: number }>();
  // 救援相关
  const [rescueOpen, setRescueOpen] = useState(false);
  const [rescueTarget, setRescueTarget] = useState<VolumeInfo | null>(null);
  const [rescueForm] = Form.useForm<RescueFormValues>();
  const [rescueInstances, setRescueInstances] = useState<Instance[]>([]);
  const [rescueLoading, setRescueLoading] = useState(false);
  const [rescuedMap, setRescuedMap] = useState<Record<string, string[]>>(loadRescued);

  const tenantName = tenants.find((t) => t.id === tenantId)?.name ?? '';
  const tenantProvider = tenants.find((t) => t.id === tenantId)?.provider || 'oci';
  const isAliyun = tenantProvider === 'aliyun';
  const rescuedIds = new Set(tenantId !== undefined ? rescuedMap[String(tenantId)] ?? [] : []);

  const markRescued = (volumeId: string, rescued: boolean) => {
    if (tenantId === undefined) return;
    setRescuedMap((prev) => {
      const key = String(tenantId);
      const cur = new Set(prev[key] ?? []);
      if (rescued) cur.add(volumeId);
      else cur.delete(volumeId);
      const next = { ...prev, [key]: [...cur] };
      localStorage.setItem(RESCUED_KEY, JSON.stringify(next));
      return next;
    });
  };

  const fetchVolumes = useCallback(async (tid: number, comp: string, kind: 'boot' | 'block') => {
    setLoading(true);
    try {
      setList(kind === 'boot' ? await listVolumes(tid, comp.trim() || undefined) : await listBlockVolumes(tid, comp.trim() || undefined));
    } catch {
      setList([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    listTenants()
      .then((ts) => {
        setTenants(ts);
        if (ts.length > 0) setTenantId(ts[0].id);
      })
      .catch(() => setTenants([]))
      .finally(() => setTenantsLoaded(true));
  }, []);

  useEffect(() => {
    if (tenantId !== undefined) fetchVolumes(tenantId, compartmentId, tab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  const openResize = (v: VolumeInfo) => {
    setTarget(v);
    form.setFieldsValue({ sizeGb: v.sizeGb });
    setOpen(true);
  };

  const onFinish = async (values: { sizeGb: number }) => {
    if (!target || tenantId === undefined) return;
    if (values.sizeGb <= target.sizeGb) {
      message.error('目标大小必须大于当前大小（OCI 只允许扩容）');
      return;
    }
    try {
      const updated = await resizeVolume(tenantId, target.id, values.sizeGb, tab);
      setList((prev) => prev.map((x) => (x.id === target.id ? updated : x)));
      message.success(`引导卷已扩容至 ${values.sizeGb} GB`);
      setOpen(false);
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  /** 打开救援弹窗：拉取同 AD 的运行中实例作为救援目标 */
  const openRescue = async (v: VolumeInfo) => {
    if (tenantId === undefined) return;
    setRescueTarget(v);
    rescueForm.resetFields();
    setRescueOpen(true);
    setRescueLoading(true);
    try {
      const { items } = await listInstances({ tenant_id: tenantId, page_size: 200 }, tenantName);
      setRescueInstances(items.filter((i) => i.status === 'RUNNING' && (!v.ad || i.ad === v.ad)));
    } catch {
      setRescueInstances([]);
    } finally {
      setRescueLoading(false);
    }
  };

  const onRescueFinish = async (values: RescueFormValues) => {
    if (!rescueTarget || tenantId === undefined) return;
    try {
      await rescueVolume(tenantId, rescueTarget.id, values.instanceId);
      markRescued(rescueTarget.id, true);
      message.success('救援成功：引导卷已挂载到救援实例，可 SSH 上去拷数据');
      setRescueOpen(false);
      fetchVolumes(tenantId, compartmentId, tab);
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const onUnrescue = async (v: VolumeInfo) => {
    if (tenantId === undefined) return;
    try {
      const r = await unrescueVolume(tenantId, v.id);
      markRescued(v.id, false);
      message.success(`已解除救援，卸载了 ${r.count} 个挂载`);
      fetchVolumes(tenantId, compartmentId, tab);
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const columns: ColumnsType<VolumeInfo> = [
    { title: '卷名称', dataIndex: 'name', key: 'name', width: 200 },
    {
      title: 'OCID',
      dataIndex: 'id',
      key: 'id',
      render: (v: string) => (
        <Text copyable style={{ maxWidth: 240 }} ellipsis>
          {v}
        </Text>
      ),
    },
    {
      title: '挂载实例',
      dataIndex: 'instanceId',
      key: 'instanceId',
      width: 200,
      ellipsis: true,
      render: (_: string | null, r: VolumeInfo) =>
        r.instanceId ? (
          <Tooltip title={r.instanceId}>
            <Text copyable={{ tooltips: false }}>{r.instanceName || r.instanceId.slice(-12)}</Text>
          </Tooltip>
        ) : (
          <Text type="secondary">未挂载</Text>
        ),
    },
    { title: '大小 (GB)', dataIndex: 'sizeGb', key: 'sizeGb', width: 110 },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (v: string) => <Tag color={v === 'AVAILABLE' ? 'success' : 'processing'}>{v}</Tag>,
    },
    { title: '创建时间', dataIndex: 'createdAt', key: 'createdAt', width: 170, render: (v: string | null) => v ?? '-' },
    {
      title: '操作',
      key: 'action',
      width: 170,
      render: (_, record) => (
        <Space>
          <Button type="link" size="small" onClick={() => openResize(record)}>
            扩容
          </Button>
          {tab === 'boot' && (
            <Button type="link" size="small" onClick={() => openRescue(record)}>
              救援
            </Button>
          )}
          {tab === 'boot' && rescuedIds.has(record.id) && (
            <Popconfirm
              title="确定解除救援吗？"
              description="将卸载该卷在救援实例上的挂载"
              onConfirm={() => onUnrescue(record)}
            >
              <Button type="link" size="small" danger>
                解除救援
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  if (tenantsLoaded && tenants.length === 0) {
    return (
      <Card title="卷管理">
        <Empty description="还没有租户配置，请先添加 OCI 租户">
          <Link to="/tenants">
            <Button type="primary">去添加租户</Button>
          </Link>
        </Empty>
      </Card>
    );
  }

  // 阿里云租户：走云盘/快照视图
  if (isAliyun && tenantId !== undefined) {
    return <AliyunVolumes tenantId={tenantId} />;
  }

  return (
    <Card title="卷管理">
      <Tabs
        activeKey={tab}
        onChange={(k) => {
          const next = k as 'boot' | 'block';
          setTab(next);
          if (tenantId !== undefined) fetchVolumes(tenantId, compartmentId, next);
        }}
        items={[
          { key: 'boot', label: '引导卷' },
          { key: 'block', label: '数据卷' },
        ]}
        style={{ marginBottom: 8 }}
      />
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          style={{ width: 260 }}
          placeholder="选择租户"
          value={tenantId}
          onChange={setTenantId}
          options={tenants.map((t) => ({ value: t.id, label: `${t.name}（${t.region}）` }))}
        />
        <Input
          style={{ width: 320 }}
          placeholder="Compartment OCID（默认租户根 compartment）"
          value={compartmentId}
          onChange={(e) => setCompartmentId(e.target.value)}
          allowClear
        />
        <Button
          type="primary"
          loading={loading}
          onClick={() => tenantId !== undefined && fetchVolumes(tenantId, compartmentId, tab)}
        >
          查询
        </Button>
      </Space>
      <Table<VolumeInfo>
        rowKey="id"
        columns={columns}
        dataSource={list}
        loading={loading}
        scroll={{ x: 1100 }}
        pagination={{ showTotal: (t) => `共 ${t} 个${tab === 'boot' ? '引导卷' : '数据卷'}` }}
      />
      <Modal title={`扩容引导卷：${target?.name ?? ''}`} open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={onFinish}>
          <Form.Item
            name="sizeGb"
            label="目标大小（GB）"
            rules={[{ required: true, message: '请输入目标大小' }]}
            extra="OCI 只允许扩容，不允许缩小。扩容后需在实例内自行扩展文件系统。"
          >
            <InputNumber min={1} max={32768} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title={`救援引导卷：${rescueTarget?.name ?? ''}`}
        open={rescueOpen}
        onCancel={() => setRescueOpen(false)}
        onOk={() => rescueForm.submit()}
        destroyOnClose
        okText="开始救援"
      >
        <Form<RescueFormValues> form={rescueForm} layout="vertical" onFinish={onRescueFinish}>
          <Form.Item
            name="instanceId"
            label="救援目标实例（需运行中且与卷同可用域）"
            rules={[{ required: true, message: '请选择救援目标实例' }]}
          >
            <Select
              loading={rescueLoading}
              placeholder={rescueLoading ? '正在加载实例…' : '选择救援实例'}
              options={rescueInstances.map((i) => ({ value: i.id, label: `${i.name}（${i.ad}）` }))}
              notFoundContent={rescueLoading ? '加载中…' : '没有同可用域的运行中实例'}
            />
          </Form.Item>
          <Form.Item
            name="confirmed"
            valuePropName="checked"
            rules={[
              {
                validator: (_, v) =>
                  v ? Promise.resolve() : Promise.reject(new Error('请确认已了解救援风险')),
              },
            ]}
          >
            <Checkbox>我已知晓：救援会先卸载该卷的现有挂载，再挂载到救援实例；卷若挂载在运行中实例上将被拒绝</Checkbox>
          </Form.Item>
          <Text type="secondary" style={{ fontSize: 12 }}>
            救援成功后，SSH 登录救援实例即可访问该卷数据（如 /dev/sdb），拷完数据后可用「解除救援」卸载。
          </Text>
        </Form>
      </Modal>
    </Card>
  );
}
