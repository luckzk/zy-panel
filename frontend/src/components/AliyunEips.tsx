import { useCallback, useEffect, useState } from 'react';
import {
  Button, Card, Form, InputNumber, Modal, Popconfirm, Select, Space, Table, Tag, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { listTenants, type TenantOption } from '../api/tenants';
import { listInstances } from '../api/instances';
import {
  allocateAliEip, bindAliEip, listAliEips, releaseAliEip, unbindAliEip,
  type AliEip,
} from '../api/aliyun';
import { getProviderMeta } from '../providers/registry';

const meta = getProviderMeta('aliyun');

/** 阿里云：EIP 管理（网络页内嵌） */
export default function AliyunEips({ tenantId: fixedTenantId }: { tenantId?: number }) {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number | undefined>(fixedTenantId);
  const [eips, setEips] = useState<AliEip[]>([]);
  const [loading, setLoading] = useState(false);
  const [allocOpen, setAllocOpen] = useState(false);
  const [bindTarget, setBindTarget] = useState<AliEip | null>(null);
  const [instances, setInstances] = useState<{ value: string; label: string }[]>([]);
  const [form] = Form.useForm();

  useEffect(() => {
    listTenants().then((ts) => setTenants(ts.filter((t) => t.provider === 'aliyun'))).catch(() => setTenants([]));
  }, []);

  useEffect(() => {
    if (fixedTenantId !== undefined) setTenantId(fixedTenantId);
  }, [fixedTenantId]);

  const fetch = useCallback(async (tid: number) => {
    setLoading(true);
    try {
      setEips(await listAliEips(tid));
    } catch {
      message.error('查询失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tenantId !== undefined) fetch(tenantId);
  }, [tenantId, fetch]);

  const openBind = async (e: AliEip) => {
    if (tenantId === undefined) return;
    try {
      const t = tenants.find((x) => x.id === tenantId);
      const { items } = await listInstances({ tenant_id: tenantId, page_size: 200 }, t?.name ?? '');
      setInstances(items.map((i) => ({ value: i.id, label: `${i.name}（${i.id.slice(0, 12)}…）` })));
    } catch {
      setInstances([]);
    }
    form.resetFields();
    setBindTarget(e);
  };

  const doAllocate = async () => {
    if (tenantId === undefined) return;
    const { bandwidth } = await form.validateFields();
    const r = await allocateAliEip(tenantId, bandwidth);
    message.success(`已申请 EIP：${r.ip}`);
    setAllocOpen(false);
    fetch(tenantId);
  };

  const doBind = async () => {
    if (!bindTarget || tenantId === undefined) return;
    const { instanceId } = await form.validateFields();
    await bindAliEip(tenantId, bindTarget.id, instanceId);
    message.success('EIP 绑定成功');
    setBindTarget(null);
    fetch(tenantId);
  };

  const doUnbind = async (e: AliEip) => {
    if (tenantId === undefined || !e.instance_id) return;
    await unbindAliEip(tenantId, e.id, e.instance_id);
    message.success('EIP 解绑成功');
    fetch(tenantId);
  };

  const doRelease = async (e: AliEip) => {
    if (tenantId === undefined) return;
    await releaseAliEip(tenantId, e.id);
    message.success('EIP 已释放');
    fetch(tenantId);
  };

  const columns: ColumnsType<AliEip> = [
    { title: 'IP 地址', dataIndex: 'ip', key: 'ip', width: 150, render: (v: string) => <strong>{v}</strong> },
    { title: 'AllocationId', dataIndex: 'id', key: 'id', width: 220, ellipsis: true },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 110,
      render: (v: string) => <Tag color={v === 'InUse' ? 'green' : 'blue'}>{v}</Tag>,
    },
    { title: '绑定实例', dataIndex: 'instance_id', key: 'instance', width: 200, ellipsis: true,
      render: (v: string) => v || <span style={{ color: '#999' }}>未绑定</span> },
    { title: '带宽', dataIndex: 'bandwidth', key: 'bw', width: 100, render: (v: string) => `${v} Mbps` },
    { title: '计费方式', dataIndex: 'internet_charge_type', key: 'charge', width: 140 },
    { title: '创建时间', dataIndex: 'created_at', key: 'created', width: 170 },
    {
      title: '操作', key: 'op', width: 220, fixed: 'right',
      render: (_, r) => (
        <Space>
          {r.instance_id ? (
            <Popconfirm title={`确定解绑 ${r.ip}？`} onConfirm={() => doUnbind(r)}>
              <Button size="small">解绑</Button>
            </Popconfirm>
          ) : (
            <Button size="small" type="primary" onClick={() => openBind(r)}>绑定实例</Button>
          )}
          <Popconfirm title={`确定释放 EIP ${r.ip}？释放后 IP 无法找回`} onConfirm={() => doRelease(r)}>
            <Button size="small" danger disabled={!!r.instance_id}>释放</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title={
        <Space>
          弹性公网 IP（EIP）
          <Tag color={meta.color}>{meta.short}</Tag>
        </Space>
      }
      extra={
        <Button type="primary" disabled={tenantId === undefined} onClick={() => { form.resetFields(); form.setFieldsValue({ bandwidth: 5 }); setAllocOpen(true); }}>
          申请 EIP
        </Button>
      }
    >
      {fixedTenantId === undefined && (
        <Select
          style={{ width: 260, marginBottom: 16 }}
          placeholder="选择阿里云租户"
          value={tenantId}
          onChange={setTenantId}
          options={tenants.map((t) => ({ value: t.id, label: `${t.name}（${t.region}）` }))}
        />
      )}
      <Table<AliEip>
        rowKey="id" columns={columns} dataSource={eips} loading={loading}
        scroll={{ x: 1300 }} pagination={{ showTotal: (t) => `共 ${t} 个 EIP` }}
      />

      <Modal title="申请 EIP（按量付费 · 按流量计费）" open={allocOpen} onOk={doAllocate} onCancel={() => setAllocOpen(false)} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item label="带宽上限（Mbps，1-500）" name="bandwidth" rules={[{ required: true }]}>
            <InputNumber min={1} max={500} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={`绑定 EIP ${bindTarget?.ip}`} open={!!bindTarget} onOk={doBind} onCancel={() => setBindTarget(null)} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item label="目标实例" name="instanceId" rules={[{ required: true, message: '请选择实例' }]}>
            <Select placeholder="选择要绑定的 ECS 实例" options={instances} showSearch optionFilterProp="label" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
