import { useCallback, useEffect, useState } from 'react';
import {
  Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Table, Tag, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { listTenants, type TenantOption } from '../api/tenants';
import {
  createAliSnapshot, deleteAliSnapshot, listAliDisks, listAliSnapshots, resizeAliDisk,
  type AliDisk, type AliSnapshot,
} from '../api/aliyun';
import { getProviderMeta } from '../providers/registry';

const meta = getProviderMeta('aliyun');

/** 阿里云：云盘 + 快照（卷管理页内嵌）。传入 tenantId 则锁定该租户并隐藏选择器。 */
export default function AliyunVolumes({ tenantId: fixedTenantId }: { tenantId?: number }) {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number | undefined>(fixedTenantId);
  const [tab, setTab] = useState<'disk' | 'snapshot'>('disk');
  const [disks, setDisks] = useState<AliDisk[]>([]);
  const [snapshots, setSnapshots] = useState<AliSnapshot[]>([]);
  const [loading, setLoading] = useState(false);
  const [resizeTarget, setResizeTarget] = useState<AliDisk | null>(null);
  const [snapTarget, setSnapTarget] = useState<AliDisk | null>(null);
  const [form] = Form.useForm();

  useEffect(() => {
    listTenants().then((ts) => setTenants(ts.filter((t) => t.provider === 'aliyun'))).catch(() => setTenants([]));
  }, []);

  useEffect(() => {
    if (fixedTenantId !== undefined) setTenantId(fixedTenantId);
  }, [fixedTenantId]);

  const fetch = useCallback(async (tid: number, t: 'disk' | 'snapshot') => {
    setLoading(true);
    try {
      if (t === 'disk') setDisks(await listAliDisks(tid));
      else setSnapshots(await listAliSnapshots(tid));
    } catch {
      message.error('查询失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tenantId !== undefined) fetch(tenantId, tab);
  }, [tenantId, tab, fetch]);

  const doResize = async () => {
    if (!resizeTarget || tenantId === undefined) return;
    const { sizeGb } = await form.validateFields();
    if (sizeGb <= resizeTarget.size_gb) {
      message.warning('新容量必须大于当前容量');
      return;
    }
    await resizeAliDisk(tenantId, resizeTarget.id, sizeGb);
    message.success('扩容请求已提交（云盘状态变为 In_use 后生效）');
    setResizeTarget(null);
    fetch(tenantId, 'disk');
  };

  const doSnapshot = async () => {
    if (!snapTarget || tenantId === undefined) return;
    const { name } = await form.validateFields();
    await createAliSnapshot(tenantId, snapTarget.id, name || '');
    message.success('快照创建已提交');
    setSnapTarget(null);
    if (tab === 'snapshot') fetch(tenantId, 'snapshot');
  };

  const doDeleteSnapshot = async (s: AliSnapshot) => {
    if (tenantId === undefined) return;
    await deleteAliSnapshot(tenantId, s.id);
    message.success('快照已删除');
    fetch(tenantId, 'snapshot');
  };

  const diskColumns: ColumnsType<AliDisk> = [
    { title: '云盘名称', dataIndex: 'name', key: 'name', width: 180 },
    { title: '云盘 ID', dataIndex: 'id', key: 'id', width: 220, ellipsis: true },
    { title: '容量', dataIndex: 'size_gb', key: 'size_gb', width: 90, render: (v) => `${v} GB` },
    { title: '类型', dataIndex: 'volume_type', key: 'volume_type', width: 130 },
    { title: '可用区', dataIndex: 'zone', key: 'zone', width: 150 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 110,
      render: (v: string) => <Tag color={v === 'In_use' ? 'green' : v === 'Available' ? 'blue' : 'default'}>{v}</Tag>,
    },
    {
      title: '挂载实例', dataIndex: 'attached_instance_id', key: 'attached', width: 200,
      render: (v: string | null) => v || <span style={{ color: '#999' }}>未挂载</span>,
    },
    {
      title: '操作', key: 'op', width: 200, fixed: 'right',
      render: (_, r) => (
        <Space>
          <Button size="small" onClick={() => { form.resetFields(); form.setFieldsValue({ sizeGb: r.size_gb }); setResizeTarget(r); }}>扩容</Button>
          <Button size="small" onClick={() => { form.resetFields(); setSnapTarget(r); }}>创建快照</Button>
        </Space>
      ),
    },
  ];

  const snapColumns: ColumnsType<AliSnapshot> = [
    { title: '快照名称', dataIndex: 'name', key: 'name', width: 180 },
    { title: '快照 ID', dataIndex: 'id', key: 'id', width: 220, ellipsis: true },
    { title: '源云盘', dataIndex: 'disk_name', key: 'disk', width: 180 },
    { title: '容量', dataIndex: 'size_gb', key: 'size', width: 90, render: (v) => `${v} GB` },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 110,
      render: (v: string) => <Tag color={v === 'accomplished' ? 'green' : 'processing'}>{v}</Tag>,
    },
    { title: '进度', dataIndex: 'progress', key: 'progress', width: 100 },
    { title: '创建时间', dataIndex: 'created_at', key: 'created', width: 170 },
    {
      title: '操作', key: 'op', width: 100, fixed: 'right',
      render: (_, r) => (
        <Popconfirm title={`确定删除快照 ${r.name}？`} onConfirm={() => doDeleteSnapshot(r)}>
          <Button size="small" danger>删除</Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <Card
      title={
        <Space>
          卷管理
          <Tag color={meta.color}>{meta.short}</Tag>
        </Space>
      }
    >
      <Space style={{ marginBottom: 16 }} wrap>
        {fixedTenantId === undefined && (
          <Select
            style={{ width: 260 }}
            placeholder="选择阿里云租户"
            value={tenantId}
            onChange={setTenantId}
            options={tenants.map((t) => ({ value: t.id, label: `${t.name}（${t.region}）` }))}
          />
        )}
        <Button
          type={tab === 'disk' ? 'primary' : 'default'}
          onClick={() => setTab('disk')}
        >云盘</Button>
        <Button
          type={tab === 'snapshot' ? 'primary' : 'default'}
          onClick={() => setTab('snapshot')}
        >快照</Button>
        <Button loading={loading} onClick={() => tenantId !== undefined && fetch(tenantId, tab)}>刷新</Button>
      </Space>
      {tab === 'disk' ? (
        <Table<AliDisk>
          rowKey="id" columns={diskColumns} dataSource={disks} loading={loading}
          scroll={{ x: 1200 }} pagination={{ showTotal: (t) => `共 ${t} 块云盘` }}
        />
      ) : (
        <Table<AliSnapshot>
          rowKey="id" columns={snapColumns} dataSource={snapshots} loading={loading}
          scroll={{ x: 1100 }} pagination={{ showTotal: (t) => `共 ${t} 个快照` }}
        />
      )}

      <Modal
        title={`云盘扩容（${resizeTarget?.name}）`}
        open={!!resizeTarget}
        onOk={doResize}
        onCancel={() => setResizeTarget(null)}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item label={`新容量（GB，当前 ${resizeTarget?.size_gb} GB，只允许调大）`} name="sizeGb" rules={[{ required: true, message: '请输入新容量' }]}>
            <InputNumber min={1} max={32768} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`创建快照（${snapTarget?.name}）`}
        open={!!snapTarget}
        onOk={doSnapshot}
        onCancel={() => setSnapTarget(null)}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item label="快照名称（可选）" name="name">
            <Input placeholder="留空自动生成" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
