import { useCallback, useEffect, useState } from 'react';
import {
  Button, Card, Descriptions, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Table, Tag, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { listTenants, type TenantOption } from '../api/tenants';
import {
  createAliSpotTask, deleteAliSpotTask, listAliInstanceTypes, listAliPublicImages,
  listAliSpotTasks, listAliVSwitches, pauseAliSpotTask, startAliSpotTask,
  type AliSpotTask, type AliSpotTaskInput,
} from '../api/aliyun';
import { getProviderMeta } from '../providers/registry';

const meta = getProviderMeta('aliyun');

const STATUS_COLOR: Record<string, string> = {
  pending: 'default', running: 'processing', paused: 'warning', success: 'success', failed: 'error',
};
const STATUS_TEXT: Record<string, string> = {
  pending: '待启动', running: '抢购中', paused: '已暂停', success: '成功', failed: '失败',
};

/** 阿里云抢占式实例任务（对标 OCI 抢机） */
export default function AliyunSpot() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number>();
  const [tasks, setTasks] = useState<AliSpotTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [logTask, setLogTask] = useState<AliSpotTask | null>(null);
  const [form] = Form.useForm();

  // 表单级联数据
  const [zones, setZones] = useState<{ value: string; label: string }[]>([]);
  const [instanceTypes, setInstanceTypes] = useState<{ value: string; label: string }[]>([]);
  const [images, setImages] = useState<{ value: string; label: string }[]>([]);
  const [vswitches, setVswitches] = useState<{ value: string; label: string }[]>([]);

  const tenant = tenants.find((t) => t.id === tenantId);

  useEffect(() => {
    listTenants().then((ts) => {
      const alis = ts.filter((t) => t.provider === 'aliyun');
      setTenants(alis);
      if (alis.length > 0) setTenantId(alis[0].id);
    }).catch(() => setTenants([]));
  }, []);

  const fetchTasks = useCallback(async (tid: number) => {
    setLoading(true);
    try {
      setTasks(await listAliSpotTasks(tid));
    } catch {
      message.error('查询失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tenantId !== undefined) fetchTasks(tenantId);
  }, [tenantId, fetchTasks]);

  // 定时刷新运行中任务的状态
  useEffect(() => {
    if (tenantId === undefined) return;
    if (!tasks.some((t) => t.status === 'running')) return;
    const timer = setInterval(() => fetchTasks(tenantId), 10000);
    return () => clearInterval(timer);
  }, [tenantId, tasks, fetchTasks]);

  /** 打开新建弹窗：拉取级联数据 */
  const openModal = async () => {
    if (tenantId === undefined || !tenant) return;
    form.resetFields();
    form.setFieldsValue({
      region_id: tenant.region, spot_strategy: 'SpotWithPriceLimit',
      system_disk_category: 'cloud_essd', system_disk_size: 40,
      bandwidth_out: 5, interval_sec: 60, max_attempts: 0,
    });
    try {
      const [types, imgs, vsws] = await Promise.all([
        listAliInstanceTypes(tenantId),
        listAliPublicImages(tenantId),
        listAliVSwitches(tenantId),
      ]);
      const zs = [...new Set(vsws.map((v) => v.zone_id).filter(Boolean))];
      setZones(zs.map((z) => ({ value: z, label: z })));
      setInstanceTypes(types.slice(0, 300).map((t) => ({
        value: t.id, label: `${t.id}（${t.cpu}C/${t.memory_gb}G）`,
      })));
      setImages(imgs.map((i) => ({ value: i.id, label: `${i.name.slice(0, 45)} [${i.architecture}]` })));
      setVswitches(vsws.map((v) => ({ value: v.id, label: `${v.name}（${v.zone_id}）` })));
    } catch {
      message.error('拉取基础数据失败');
      return;
    }
    setModalOpen(true);
  };

  const onZoneChange = async (zoneId: string) => {
    if (tenantId === undefined) return;
    form.setFieldsValue({ vswitch_id: undefined });
    try {
      const vsws = await listAliVSwitches(tenantId, zoneId);
      setVswitches(vsws.map((v) => ({ value: v.id, label: `${v.name}（${v.cidr}）` })));
    } catch { /* 忽略 */ }
  };

  const onFinish = async (values: Record<string, unknown>) => {
    if (tenantId === undefined) return;
    const body: AliSpotTaskInput = {
      tenant_id: tenantId,
      name: String(values.name),
      region_id: String(values.region_id),
      zone_id: String(values.zone_id || ''),
      instance_type: String(values.instance_type),
      image_id: String(values.image_id),
      vswitch_id: String(values.vswitch_id),
      security_group_id: String(values.security_group_id),
      spot_strategy: String(values.spot_strategy || 'SpotWithPriceLimit'),
      spot_price_limit: values.spot_price_limit ? String(values.spot_price_limit) : undefined,
      system_disk_category: String(values.system_disk_category || 'cloud_essd'),
      system_disk_size: Number(values.system_disk_size || 40),
      bandwidth_out: Number(values.bandwidth_out || 5),
      instance_name: String(values.instance_name || 'panel-spot'),
      interval_sec: Number(values.interval_sec || 60),
      max_attempts: Number(values.max_attempts || 0),
    };
    await createAliSpotTask(body);
    message.success('抢占式任务已创建，可在列表中启动');
    setModalOpen(false);
    fetchTasks(tenantId);
  };

  const doStart = async (t: AliSpotTask) => {
    await startAliSpotTask(t.id);
    message.success('任务已启动，后台开始轮询创建');
    if (tenantId !== undefined) fetchTasks(tenantId);
  };

  const doPause = async (t: AliSpotTask) => {
    await pauseAliSpotTask(t.id);
    message.success('任务已暂停');
    if (tenantId !== undefined) fetchTasks(tenantId);
  };

  const doDelete = async (t: AliSpotTask) => {
    await deleteAliSpotTask(t.id);
    message.success('任务已删除');
    if (tenantId !== undefined) fetchTasks(tenantId);
  };

  const columns: ColumnsType<AliSpotTask> = [
    { title: '任务名称', dataIndex: 'name', key: 'name', width: 160 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (v: string) => <Tag color={STATUS_COLOR[v] || 'default'}>{STATUS_TEXT[v] || v}</Tag>,
    },
    { title: '规格', dataIndex: 'instance_type', key: 'type', width: 170 },
    {
      title: '策略', dataIndex: 'spot_strategy', key: 'strategy', width: 150,
      render: (v: string, r) => v === 'SpotWithPriceLimit' ? `限价 $${r.spot_price_limit}/时` : '随用随付价',
    },
    {
      title: '尝试', key: 'attempts', width: 100,
      render: (_, r) => `${r.attempts}${r.max_attempts > 0 ? ` / ${r.max_attempts}` : ' / ∞'}`,
    },
    { title: '创建实例', dataIndex: 'created_instance_id', key: 'iid', width: 200, ellipsis: true,
      render: (v: string | null) => v || '-' },
    { title: '最后错误', dataIndex: 'last_error', key: 'err', ellipsis: true,
      render: (v: string | null) => v ? <span style={{ color: '#cf1322' }}>{v.slice(0, 80)}</span> : '-' },
    {
      title: '操作', key: 'op', width: 260, fixed: 'right',
      render: (_, r) => (
        <Space>
          {r.status === 'running' ? (
            <Button size="small" onClick={() => doPause(r)}>暂停</Button>
          ) : (
            <Button size="small" type="primary" disabled={r.status === 'success'} onClick={() => doStart(r)}>启动</Button>
          )}
          <Button size="small" onClick={() => setLogTask(r)} disabled={r.recent_logs.length === 0 && r.attempts === 0}>
            日志{r.recent_logs.length > 0 ? `(${r.recent_logs.length})` : ''}
          </Button>
          <Popconfirm title={`确定删除任务 ${r.name}？`} onConfirm={() => doDelete(r)}>
            <Button size="small" danger disabled={r.status === 'running'}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Card
        title={
          <Space>
            抢占式实例任务
            <Tag color={meta.color}>{meta.short}</Tag>
          </Space>
        }
        extra={<Button type="primary" disabled={tenantId === undefined} onClick={openModal}>新建任务</Button>}
      >
        <Select
          style={{ width: 280, marginBottom: 16 }}
          placeholder="选择阿里云租户"
          value={tenantId}
          onChange={setTenantId}
          options={tenants.map((t) => ({ value: t.id, label: `${t.name}（${t.region}）` }))}
        />
        <Table<AliSpotTask>
          rowKey="id" columns={columns} dataSource={tasks} loading={loading}
          scroll={{ x: 1400 }} pagination={{ showTotal: (t) => `共 ${t} 个任务` }}
        />
      </Card>

      <Modal
        title="新建抢占式任务"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
        width={640}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={onFinish}>
          <Form.Item label="任务名称" name="name" rules={[{ required: true }]}>
            <Input placeholder="如：抢占计算型-4C8G" />
          </Form.Item>
          <Form.Item label="地域" name="region_id" rules={[{ required: true }]}>
            <Input disabled />
          </Form.Item>
          <Space style={{ width: '100%' }} size={12}>
            <Form.Item label="可用区" name="zone_id" style={{ flex: 1 }}>
              <Select placeholder="可选，不选则由阿里云分配" allowClear options={zones} onChange={onZoneChange} />
            </Form.Item>
            <Form.Item label="实例规格" name="instance_type" rules={[{ required: true }]} style={{ flex: 2 }}>
              <Select placeholder="选择规格" showSearch optionFilterProp="label" options={instanceTypes} />
            </Form.Item>
          </Space>
          <Form.Item label="镜像" name="image_id" rules={[{ required: true }]}>
            <Select placeholder="选择公共镜像" showSearch optionFilterProp="label" options={images} />
          </Form.Item>
          <Space style={{ width: '100%' }} size={12}>
            <Form.Item label="交换机" name="vswitch_id" rules={[{ required: true }]} style={{ flex: 1 }}>
              <Select placeholder="选择交换机" options={vswitches} />
            </Form.Item>
            <Form.Item
              label="安全组 ID" name="security_group_id" rules={[{ required: true }]}
              style={{ flex: 1 }} tooltip="在实例管理的安全组页可查看安全组 ID"
            >
              <Input placeholder="sg-xxxxxxxx" />
            </Form.Item>
          </Space>
          <Space style={{ width: '100%' }} size={12}>
            <Form.Item label="竞价策略" name="spot_strategy" style={{ flex: 1 }}>
              <Select options={[
                { value: 'SpotWithPriceLimit', label: '设置上限价格' },
                { value: 'SpotAsPriceGo', label: '自动出价（按量付费价）' },
              ]} />
            </Form.Item>
            <Form.Item
              label="最高出价（$/小时）" name="spot_price_limit" style={{ flex: 1 }}
              dependencies={['spot_strategy']}
              rules={[({ getFieldValue }) => ({
                validator(_, v) {
                  if (getFieldValue('spot_strategy') !== 'SpotWithPriceLimit') return Promise.resolve();
                  if (!v) return Promise.reject(new Error('限价策略必填'));
                  return Promise.resolve();
                },
              })]}
            >
              <Input placeholder="如 0.05" />
            </Form.Item>
          </Space>
          <Space style={{ width: '100%' }} size={12}>
            <Form.Item label="系统盘类型" name="system_disk_category" style={{ flex: 1 }}>
              <Select options={[
                { value: 'cloud_essd', label: 'ESSD 云盘' },
                { value: 'cloud_efficiency', label: '高效云盘' },
                { value: 'cloud_ssd', label: 'SSD 云盘' },
              ]} />
            </Form.Item>
            <Form.Item label="系统盘大小(GB)" name="system_disk_size" style={{ flex: 1 }}>
              <InputNumber min={20} max={500} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="公网带宽(Mbps)" name="bandwidth_out" style={{ flex: 1 }}>
              <InputNumber min={0} max={100} style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Space style={{ width: '100%' }} size={12}>
            <Form.Item label="实例名" name="instance_name" style={{ flex: 1 }}>
              <Input />
            </Form.Item>
            <Form.Item label="轮询间隔(秒)" name="interval_sec" style={{ flex: 1 }}>
              <InputNumber min={30} max={3600} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="最大尝试(0=不限)" name="max_attempts" style={{ flex: 1 }}>
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Form.Item>
            <Button type="primary" htmlType="submit" block>创建任务</Button>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`任务日志：${logTask?.name}`}
        open={!!logTask}
        onCancel={() => setLogTask(null)}
        footer={null}
        width={640}
      >
        <div style={{ maxHeight: 400, overflowY: 'auto', background: '#0f172a', borderRadius: 8, padding: 12 }}>
          {(logTask?.recent_logs ?? []).map((l, i) => (
            <div key={i} style={{ fontFamily: 'monospace', fontSize: 12, color: l.ok ? '#4ade80' : '#f87171', marginBottom: 6 }}>
              [{l.time}] {l.ok ? `成功，实例 ${l.instance_id}` : l.error}
            </div>
          ))}
          {(logTask?.recent_logs ?? []).length === 0 && (
            <div style={{ color: '#64748b', fontSize: 12 }}>暂无尝试记录</div>
          )}
        </div>
        {logTask?.last_error && (
          <Descriptions column={1} size="small" style={{ marginTop: 12 }}>
            <Descriptions.Item label="最后错误">{logTask.last_error}</Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  );
}
