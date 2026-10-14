import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Radio,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  message,
} from 'antd';
import { PlusOutlined, SearchOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { SnatchStatus, SnatchTask } from '../types';
import { listTenants, type TenantOption } from '../api/tenants';
import {
  getAvailabilityDomains,
  getBootVolumes,
  getCompartments,
  getImages,
  getShapes,
  getSubnets,
  type AvailabilityDomain,
  type BootVolume,
  type Compartment,
  type Image,
  type Shape,
  type Subnet,
} from '../api/meta';
import {
  createSnatchTask,
  deleteSnatchTask,
  getSnatchStats,
  listSnatchTasks,
  pauseSnatchTask,
  resumeSnatchTask,
  startSnatchTask,
  type SnatchStats,
  type SnatchTaskCreate,
} from '../api/snatch';

const { TextArea } = Input;

/** 抢机任务状态机标签 */
const STATUS_META: Record<SnatchStatus, { color: string; text: string }> = {
  pending: { color: 'default', text: '等待中' },
  running: { color: 'processing', text: '抢机中' },
  paused: { color: 'warning', text: '已暂停' },
  success: { color: 'success', text: '已成功' },
  failed: { color: 'error', text: '失败' },
};

interface SnatchFormValues {
  name: string;
  tenant_id: number;
  compartment_id: string;
  source_type: 'image' | 'bootVolume'; // 启动源：镜像 / 现有引导卷
  image_id: string;
  boot_volume_id?: string;
  subnet_id: string;
  availability_domain: string;
  availability_domains?: string[]; // 多 AD 轮询（下拉多选）
  shape: string;
  ocpus?: number | null;
  memory_in_gbs?: number | null;
  display_name?: string;
  assign_public_ip?: boolean;
  ssh_public_key?: string;
  interval_sec: number;
  max_attempts?: number;
}

/** 抢机任务页：真实接口联调 */
export default function SnatchTasks() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [list, setList] = useState<SnatchTask[]>([]);
  const [stats, setStats] = useState<SnatchStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [statusFilter, setStatusFilter] = useState<SnatchStatus>();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm<SnatchFormValues>();
  const shape = Form.useWatch('shape', form);
  const watchTenantId = Form.useWatch('tenant_id', form);
  const watchCompartmentId = Form.useWatch('compartment_id', form);
  const watchSourceType = Form.useWatch('source_type', form);
  const watchBootVolumeId = Form.useWatch('boot_volume_id', form);
  const isBootVolume = watchSourceType === 'bootVolume';

  // 选引导卷后：AD 自动锁定为该卷所在 AD（从引导卷起实例必须同 AD），清空多 AD 轮询
  useEffect(() => {
    if (!isBootVolume || !watchBootVolumeId) return;
    const vol = meta.bootVolumes.find((v) => v.id === watchBootVolumeId);
    if (vol?.availability_domain) {
      form.setFieldsValue({ availability_domain: vol.availability_domain, availability_domains: [] });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watchBootVolumeId, isBootVolume]);

  // 下拉元数据：全部来自 OCI 实时接口（租户→compartment/AD，compartment→shape/镜像/子网/引导卷）
  const [meta, setMeta] = useState<{
    compartments: Compartment[];
    ads: AvailabilityDomain[];
    shapes: Shape[];
    images: Image[];
    subnets: Subnet[];
    bootVolumes: BootVolume[];
  }>({ compartments: [], ads: [], shapes: [], images: [], subnets: [], bootVolumes: [] });
  const [metaLoading, setMetaLoading] = useState(false);

  // 租户变化 → 拉 compartments + AD，清空下游字段
  useEffect(() => {
    if (!open || !watchTenantId) return;
    let cancelled = false;
    setMetaLoading(true);
    Promise.allSettled([getCompartments(watchTenantId), getAvailabilityDomains(watchTenantId)]).then(
      ([c, a]) => {
        if (cancelled) return;
        setMeta((m) => ({
          ...m,
          compartments: c.status === 'fulfilled' ? c.value : [],
          ads: a.status === 'fulfilled' ? a.value : [],
          shapes: [],
          images: [],
          subnets: [],
          bootVolumes: [],
        }));
        if (c.status === 'rejected' || a.status === 'rejected') {
          message.error('Compartment / 可用域加载失败，请检查租户连通性');
        }
        setMetaLoading(false);
      },
    );
    form.setFieldsValue({
      compartment_id: undefined,
      availability_domain: undefined,
      availability_domains: undefined,
      shape: undefined,
      image_id: undefined,
      boot_volume_id: undefined,
      subnet_id: undefined,
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, watchTenantId]);

  // Compartment 变化 → 拉 shape + 镜像 + 子网 + 引导卷，清空下游字段
  useEffect(() => {
    if (!open || !watchTenantId || !watchCompartmentId) return;
    let cancelled = false;
    setMetaLoading(true);
    Promise.allSettled([
      getShapes(watchTenantId, watchCompartmentId),
      getImages(watchTenantId, watchCompartmentId),
      getSubnets(watchTenantId, watchCompartmentId),
      getBootVolumes(watchTenantId, watchCompartmentId),
    ]).then(([s, i, n, b]) => {
      if (cancelled) return;
      setMeta((m) => ({
        ...m,
        shapes: s.status === 'fulfilled' ? s.value : [],
        images: i.status === 'fulfilled' ? i.value : [],
        subnets: n.status === 'fulfilled' ? n.value : [],
        bootVolumes: b.status === 'fulfilled' ? b.value : [],
      }));
      if (s.status === 'rejected' || i.status === 'rejected' || n.status === 'rejected') {
        message.error('Shape / 镜像 / 子网加载失败，请检查租户连通性');
      }
      if (b.status === 'rejected') {
        message.warning('引导卷列表加载失败，从引导卷抢机不可用');
      }
      setMetaLoading(false);
    });
    form.setFieldsValue({ shape: undefined, image_id: undefined, boot_volume_id: undefined, subnet_id: undefined });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, watchTenantId, watchCompartmentId]);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const ts = await listTenants();
      setTenants(ts);
      const [tasks, st] = await Promise.all([listSnatchTasks(ts), getSnatchStats()]);
      setList(tasks);
      setStats(st);
    } catch {
      setList([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const filtered = useMemo(
    () =>
      list.filter(
        (t) =>
          (!keyword || t.name.includes(keyword)) && (!statusFilter || t.status === statusFilter),
      ),
    [list, keyword, statusFilter],
  );

  const doAction = async (fn: () => Promise<void>, okMsg: string) => {
    try {
      await fn();
      message.success(okMsg);
      fetchAll();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const onFinish = async (values: SnatchFormValues) => {
    const ads = (values.availability_domains ?? []).filter(Boolean);
    const useBootVolume = values.source_type === 'bootVolume';
    const body: SnatchTaskCreate = {
      tenant_id: values.tenant_id,
      name: values.name,
      shape: values.shape,
      compartment_id: values.compartment_id,
      image_id: useBootVolume ? '' : values.image_id,
      boot_volume_id: useBootVolume ? (values.boot_volume_id || '') : '',
      subnet_id: values.subnet_id,
      availability_domain: values.availability_domain,
      availability_domains: ads.length > 0 ? ads : undefined,
      ocpus: values.ocpus ?? null,
      memory_in_gbs: values.memory_in_gbs ?? null,
      display_name: values.display_name || '',
      assign_public_ip: values.assign_public_ip ?? true,
      ssh_public_key: values.ssh_public_key || null,
      interval_sec: values.interval_sec,
      max_attempts: values.max_attempts ?? 0,
    };
    await doAction(() => createSnatchTask(body), '抢机任务已创建，可在列表中启动');
    setOpen(false);
    form.resetFields();
  };

  const isFlex = (shape ?? '').includes('Flex');

  const columns: ColumnsType<SnatchTask> = [
    { title: '任务名称', dataIndex: 'name', key: 'name', width: 160 },
    { title: '租户', dataIndex: 'tenant', key: 'tenant', width: 120 },
    { title: 'Region', dataIndex: 'region', key: 'region', width: 130 },
    { title: '可用域', dataIndex: 'ad', key: 'ad', width: 150, ellipsis: true },
    { title: 'Shape', dataIndex: 'shape', key: 'shape', width: 190 },
    { title: '启动源', dataIndex: 'image', key: 'image', width: 170, ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v: SnatchStatus) => <Tag color={STATUS_META[v].color}>{STATUS_META[v].text}</Tag>,
    },
    { title: '已尝试', dataIndex: 'attempts', key: 'attempts', width: 90, render: (v: number) => v.toLocaleString() },
    { title: '间隔(秒)', dataIndex: 'intervalSec', key: 'intervalSec', width: 90 },
    { title: '创建时间', dataIndex: 'createdAt', key: 'createdAt', width: 170 },
    {
      title: '操作',
      key: 'action',
      width: 220,
      fixed: 'right',
      render: (_, record) => (
        <Space>
          {record.status === 'pending' && (
            <Button type="link" size="small" onClick={() => doAction(() => startSnatchTask(record.id), '任务已启动')}>
              启动
            </Button>
          )}
          {record.status === 'running' && (
            <Button type="link" size="small" onClick={() => doAction(() => pauseSnatchTask(record.id), '任务已暂停')}>
              暂停
            </Button>
          )}
          {record.status === 'paused' && (
            <Button type="link" size="small" onClick={() => doAction(() => resumeSnatchTask(record.id), '任务已继续（断点续抢）')}>
              继续
            </Button>
          )}
          <Popconfirm title="确定删除该任务吗？" onConfirm={() => doAction(() => deleteSnatchTask(record.id), '任务已删除')}>
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title="抢机任务"
      extra={
        <Space>
          <Button onClick={fetchAll}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
            新建抢机任务
          </Button>
        </Space>
      }
    >
      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          placeholder="搜索任务名称"
          prefix={<SearchOutlined />}
          allowClear
          style={{ width: 240 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <Select
          placeholder="状态筛选"
          allowClear
          style={{ width: 140 }}
          value={statusFilter}
          onChange={setStatusFilter}
          options={Object.entries(STATUS_META).map(([value, meta]) => ({ value, label: meta.text }))}
        />
      </Space>
      {stats && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Row gutter={16} align="middle">
            <Col span={4}>
              <Statistic title="任务总数" value={stats.total} />
            </Col>
            <Col span={4}>
              <Statistic title="抢机中" value={stats.by_status.running ?? 0} valueStyle={{ color: '#1677ff' }} />
            </Col>
            <Col span={4}>
              <Statistic title="已成功" value={stats.by_status.success ?? 0} valueStyle={{ color: '#52c41a' }} />
            </Col>
            <Col span={4}>
              <Statistic title="总尝试次数" value={stats.total_attempts} />
            </Col>
            <Col span={4}>
              <Statistic
                title="成功率"
                value={((stats.success_rate ?? 0) * 100).toFixed(1)}
                suffix="%"
                valueStyle={{ color: (stats.success_rate ?? 0) >= 0.5 ? '#52c41a' : '#faad14' }}
              />
            </Col>
            <Col span={4} style={{ textAlign: 'center' }}>
              <Progress
                type="circle"
                width={64}
                percent={Math.round((stats.success_rate ?? 0) * 100)}
                format={(p) => `${p}%`}
              />
            </Col>
          </Row>
        </Card>
      )}
      <Table<SnatchTask>
        rowKey="id"
        columns={columns}
        dataSource={filtered}
        loading={loading}
        scroll={{ x: 1500 }}
        pagination={{ showSizeChanger: true, showTotal: (t) => `共 ${t} 个任务` }}
        expandable={{
          expandedRowRender: (r) => (
            <div
              style={{
                background: '#0d1117',
                color: '#c9d1d9',
                borderRadius: 6,
                padding: '8px 12px',
                fontSize: 12,
                fontFamily: 'Menlo, Consolas, monospace',
                whiteSpace: 'pre-wrap',
                maxHeight: 240,
                overflowY: 'auto',
              }}
            >
              {r.recentLogs.length > 0 ? r.recentLogs.join('\n') : '暂无尝试记录'}
            </div>
          ),
          rowExpandable: (r) => r.attempts > 0,
        }}
      />
      <Modal
        title="新建抢机任务"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        destroyOnClose
        width={640}
      >
        <Form<SnatchFormValues>
          form={form}
          layout="vertical"
          onFinish={onFinish}
          initialValues={{ interval_sec: 15, assign_public_ip: true }}
        >
          <Form.Item name="name" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]}>
            <Input placeholder="如：东京 ARM 4C24G" />
          </Form.Item>
          <Form.Item name="tenant_id" label="租户" rules={[{ required: true, message: '请选择租户' }]}>
            <Select options={tenants.map((t) => ({ label: `${t.name}（${t.region}）`, value: t.id }))} placeholder="先在租户配置中添加 OCI 租户" />
          </Form.Item>
          <Form.Item
            name="compartment_id"
            label="Compartment"
            rules={[{ required: true, message: '请选择 compartment' }]}
            tooltip="先选租户，自动拉取该租户下的 compartment 列表"
          >
            <Select
              placeholder={watchTenantId ? '选择 compartment' : '请先选择租户'}
              disabled={!watchTenantId}
              loading={metaLoading}
              showSearch
              optionFilterProp="label"
              options={meta.compartments.map((c) => ({ value: c.id, label: `${c.name} · ${c.id.slice(-12)}` }))}
            />
          </Form.Item>
          <Form.Item
            name="availability_domain"
            label="可用域（AD）"
            rules={[{ required: true, message: '请选择可用域' }]}
            tooltip={isBootVolume ? '已按所选引导卷自动锁定（从引导卷起实例必须同 AD）' : '先选租户，自动拉取该租户 home region 的可用域'}
          >
            <Select
              placeholder={watchTenantId ? '选择可用域' : '请先选择租户'}
              disabled={!watchTenantId || isBootVolume}
              loading={metaLoading}
              showSearch
              options={meta.ads.map((a) => ({ value: a.name, label: a.name }))}
            />
          </Form.Item>
          <Form.Item
            name="availability_domains"
            label="多 AD 轮询（可选）"
            tooltip={isBootVolume ? '引导卷模式不支持多 AD 轮询（卷固定在一个 AD）' : '抢机时按尝试次数轮流切换 AD，提高命中率；为空则只用上面的单个可用域'}
          >
            <Select
              mode="multiple"
              placeholder={watchTenantId ? '可多选轮询的可用域' : '请先选择租户'}
              disabled={!watchTenantId || isBootVolume}
              loading={metaLoading}
              options={meta.ads.map((a) => ({ value: a.name, label: a.name }))}
            />
          </Form.Item>
          <Form.Item name="shape" label="Shape" rules={[{ required: true, message: '请选择 Shape' }]}>
            <Select
              placeholder={watchCompartmentId ? '选择 Shape' : '请先选择 compartment'}
              disabled={!watchCompartmentId}
              loading={metaLoading}
              showSearch
              optionFilterProp="label"
              options={meta.shapes.map((s) => ({
                value: s.shape,
                label: s.is_flex && s.ocpus ? `${s.shape}（${s.ocpus} OCPU / ${s.memory_in_gbs} GB）` : s.shape,
              }))}
            />
          </Form.Item>
          {isFlex && (
            <>
              <Space style={{ display: 'flex' }} size={16}>
                <Form.Item name="ocpus" label="OCPU 数" rules={[{ required: true, message: 'Flex 机型必填' }]} style={{ flex: 1 }}>
                  <InputNumber min={1} max={64} style={{ width: '100%' }} placeholder="如：4" />
                </Form.Item>
                <Form.Item name="memory_in_gbs" label="内存（GB）" rules={[{ required: true, message: 'Flex 机型必填' }]} style={{ flex: 1 }}>
                  <InputNumber min={1} max={1024} style={{ width: '100%' }} placeholder="如：24" />
                </Form.Item>
              </Space>
            </>
          )}
          <Form.Item
            name="source_type"
            label="启动源"
            initialValue="image"
            tooltip="从镜像新建：全新系统盘；从现有引导卷：保留原来系统盘的数据（如实例被回收后用旧系统盘重起）"
          >
            <Radio.Group
              options={[
                { value: 'image', label: '镜像（全新系统）' },
                { value: 'bootVolume', label: '现有引导卷（保留数据）' },
              ]}
              onChange={() => {
                form.setFieldsValue({ image_id: undefined, boot_volume_id: undefined });
              }}
            />
          </Form.Item>
          {!isBootVolume && (
            <Form.Item
              name="image_id"
              label="镜像"
              rules={[{ required: true, message: '请选择镜像' }]}
              tooltip="先选 compartment，自动拉取可用镜像（按创建时间倒序）"
            >
              <Select
                placeholder={watchCompartmentId ? '搜索并选择镜像' : '请先选择 compartment'}
                disabled={!watchCompartmentId}
                loading={metaLoading}
                showSearch
                optionFilterProp="label"
                options={meta.images.map((img) => ({
                  value: img.id,
                  label: `${img.display_name}（${img.operating_system} ${img.operating_system_version}）`,
                }))}
              />
            </Form.Item>
          )}
          {isBootVolume && (
            <Form.Item
              name="boot_volume_id"
              label="引导卷"
              rules={[{ required: true, message: '请选择引导卷' }]}
              tooltip="只列出 AVAILABLE 状态的引导卷；所选卷的 AD 会自动填入可用域（必须同 AD）"
            >
              <Select
                placeholder={watchCompartmentId ? '搜索并选择引导卷' : '请先选择 compartment'}
                disabled={!watchCompartmentId}
                loading={metaLoading}
                showSearch
                optionFilterProp="label"
                options={meta.bootVolumes.map((v) => ({
                  value: v.id,
                  label: `${v.display_name || '(未命名)'} · ${v.size_in_gbs}GB · ${v.availability_domain}`,
                }))}
              />
            </Form.Item>
          )}
          <Form.Item
            name="subnet_id"
            label="子网"
            rules={[{ required: true, message: '请选择子网' }]}
            tooltip="先选 compartment，自动拉取可用子网"
          >
            <Select
              placeholder={watchCompartmentId ? '选择子网' : '请先选择 compartment'}
              disabled={!watchCompartmentId}
              loading={metaLoading}
              showSearch
              optionFilterProp="label"
              options={meta.subnets.map((s) => ({
                value: s.id,
                label: `${s.display_name} · ${s.cidr_block}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="display_name" label="实例显示名（可选）">
            <Input placeholder="为空则自动生成：任务名-尝试次数" />
          </Form.Item>
          <Form.Item name="ssh_public_key" label="SSH 公钥（可选）" tooltip="实例创建后用于 SSH 登录">
            <TextArea rows={3} placeholder="ssh-rsa AAAAB3..." />
          </Form.Item>
          <Space style={{ display: 'flex' }} size={16}>
            <Form.Item name="assign_public_ip" label="分配公网 IP" valuePropName="checked" style={{ flex: 1 }}>
              <Switch />
            </Form.Item>
            <Form.Item name="interval_sec" label="抢机间隔（秒）" rules={[{ required: true }]} style={{ flex: 1 }}>
              <InputNumber min={10} max={3600} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="max_attempts" label="最大尝试次数（0=不限）" style={{ flex: 1 }}>
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </Card>
  );
}
