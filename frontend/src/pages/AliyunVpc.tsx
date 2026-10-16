import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { listTenants, listTenantRegions, type TenantOption } from '../api/tenants';
import {
  createAliVpc,
  createAliVSwitch,
  deleteAliVpc,
  deleteAliVSwitch,
  listAliVpcs,
  listAliVSwitchesFull,
  type AliVpc,
  type AliVSwitch,
} from '../api/aliyun';

const { Text } = Typography;

interface VpcFormValues {
  name: string;
  cidr: string;
  description: string;
}

interface VSwitchFormValues {
  vpc_id: string;
  zone_id: string;
  cidr: string;
  name: string;
  description: string;
}

const statusTag = (status: string) => {
  const s = (status || '').toLowerCase();
  if (s === 'available') return <Tag color="success">可用</Tag>;
  if (s === 'pending') return <Tag color="processing">创建中</Tag>;
  return <Tag>{status || '—'}</Tag>;
};

/** 阿里云 VPC 网络管理：VPC / 交换机 */
export default function AliyunVpc() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number>();
  const [regions, setRegions] = useState<{ value: string; label: string }[]>([]);
  const [regionId, setRegionId] = useState<string>();
  const [vpcs, setVpcs] = useState<AliVpc[]>([]);
  const [vswitches, setVswitches] = useState<AliVSwitch[]>([]);
  const [vswitchVpcId, setVswitchVpcId] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [tenantsLoaded, setTenantsLoaded] = useState(false);
  const [vpcOpen, setVpcOpen] = useState(false);
  const [vswitchOpen, setVswitchOpen] = useState(false);
  const [vpcForm] = Form.useForm<VpcFormValues>();
  const [vswitchForm] = Form.useForm<VSwitchFormValues>();

  useEffect(() => {
    listTenants()
      .then((ts) => {
        const ali = ts.filter((t) => t.provider === 'aliyun');
        setTenants(ali);
        if (ali.length > 0) setTenantId(ali[0].id);
      })
      .catch(() => setTenants([]))
      .finally(() => setTenantsLoaded(true));
  }, []);

  // 地域列表：运行时拉取（非写死）
  useEffect(() => {
    if (tenantId === undefined) return;
    listTenantRegions(tenantId)
      .then((rs) => setRegions(rs.map((r) => ({ value: r.id, label: `${r.name}（${r.id}）` }))))
      .catch(() => setRegions([]));
  }, [tenantId]);

  const fetchVpcs = useCallback(async (tid: number, region?: string) => {
    setLoading(true);
    try {
      const vs = await listAliVpcs(tid, region);
      setVpcs(vs);
      setVswitchVpcId((cur) => (vs.some((v) => v.id === cur) ? cur : vs[0]?.id));
    } catch {
      setVpcs([]);
      message.error('VPC 查询失败');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchVSwitches = useCallback(async (tid: number, vpcId: string | undefined, region?: string) => {
    setLoading(true);
    try {
      setVswitches(await listAliVSwitchesFull(tid, vpcId, region));
    } catch {
      setVswitches([]);
      message.error('交换机查询失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tenantId !== undefined) fetchVpcs(tenantId, regionId);
  }, [tenantId, regionId, fetchVpcs]);

  useEffect(() => {
    if (tenantId !== undefined) fetchVSwitches(tenantId, vswitchVpcId, regionId);
  }, [tenantId, vswitchVpcId, regionId, fetchVSwitches]);

  const refresh = () => {
    if (tenantId !== undefined) {
      fetchVpcs(tenantId, regionId);
      fetchVSwitches(tenantId, vswitchVpcId, regionId);
    }
  };

  const onCreateVpc = async () => {
    if (tenantId === undefined) return;
    const v = await vpcForm.validateFields();
    const r = await createAliVpc(
      tenantId,
      { name: v.name.trim(), cidr: v.cidr.trim(), description: v.description?.trim() || '' },
      regionId,
    );
    message.success(`VPC 已创建：${r.vpc_id}`);
    setVpcOpen(false);
    fetchVpcs(tenantId, regionId);
  };

  const onDeleteVpc = async (id: string) => {
    if (tenantId === undefined) return;
    await deleteAliVpc(tenantId, id, regionId);
    message.success('VPC 已删除');
    fetchVpcs(tenantId, regionId);
  };

  const onCreateVSwitch = async () => {
    if (tenantId === undefined) return;
    const v = await vswitchForm.validateFields();
    const r = await createAliVSwitch(
      tenantId,
      {
        vpc_id: v.vpc_id,
        zone_id: v.zone_id.trim(),
        cidr: v.cidr.trim(),
        name: v.name?.trim() || undefined,
        description: v.description?.trim() || undefined,
      },
      regionId,
    );
    message.success(`交换机已创建：${r.vswitch_id}`);
    setVswitchOpen(false);
    fetchVSwitches(tenantId, vswitchVpcId, regionId);
  };

  const onDeleteVSwitch = async (id: string) => {
    if (tenantId === undefined) return;
    await deleteAliVSwitch(tenantId, id, regionId);
    message.success('交换机已删除');
    fetchVSwitches(tenantId, vswitchVpcId, regionId);
  };

  const openVSwitchModal = () => {
    vswitchForm.resetFields();
    if (vswitchVpcId) vswitchForm.setFieldValue('vpc_id', vswitchVpcId);
    setVswitchOpen(true);
  };

  const vpcColumns: ColumnsType<AliVpc> = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: 'VPC ID',
      dataIndex: 'id',
      key: 'id',
      render: (v: string) => <Text copyable code>{v}</Text>,
    },
    { title: 'CIDR', dataIndex: 'cidr', key: 'cidr', render: (v: string) => <Text code>{v}</Text> },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: statusTag },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, r) => (
        <Popconfirm title="确定删除这个 VPC 吗？" onConfirm={() => onDeleteVpc(r.id)}>
          <Button size="small" danger>
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  const vswitchColumns: ColumnsType<AliVSwitch> = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '交换机 ID',
      dataIndex: 'id',
      key: 'id',
      render: (v: string) => <Text copyable code>{v}</Text>,
    },
    { title: 'CIDR', dataIndex: 'cidr', key: 'cidr', render: (v: string) => <Text code>{v}</Text> },
    { title: '可用区', dataIndex: 'zone_id', key: 'zone_id' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: statusTag },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, r) => (
        <Popconfirm title="确定删除这个交换机吗？" onConfirm={() => onDeleteVSwitch(r.id)}>
          <Button size="small" danger>
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  if (tenantsLoaded && tenants.length === 0) {
    return (
      <Card title="VPC 网络">
        <Empty description="还没有阿里云租户，请先添加" />
      </Card>
    );
  }

  return (
    <Card title="VPC 网络">
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          style={{ width: 240 }}
          placeholder="选择阿里云租户"
          value={tenantId}
          onChange={setTenantId}
          options={tenants.map((t) => ({ value: t.id, label: t.name }))}
        />
        <Select
          style={{ width: 240 }}
          placeholder="地域（默认租户地域）"
          allowClear
          value={regionId}
          onChange={setRegionId}
          options={regions}
          showSearch
          optionFilterProp="label"
        />
        <Button onClick={refresh} loading={loading}>
          刷新
        </Button>
      </Space>
      <Tabs
        defaultActiveKey="vpc"
        items={[
          {
            key: 'vpc',
            label: 'VPC',
            children: (
              <>
                <Button
                  type="primary"
                  icon={<PlusOutlined />}
                  onClick={() => setVpcOpen(true)}
                  style={{ marginBottom: 16 }}
                >
                  新建 VPC
                </Button>
                <Table<AliVpc>
                  rowKey="id"
                  columns={vpcColumns}
                  dataSource={vpcs}
                  loading={loading}
                  pagination={{ showTotal: (t) => `共 ${t} 个 VPC` }}
                  locale={{ emptyText: '暂无 VPC，点击「新建 VPC」创建' }}
                />
              </>
            ),
          },
          {
            key: 'vswitch',
            label: '交换机',
            children: (
              <>
                <Space style={{ marginBottom: 16 }} wrap>
                  <Select
                    style={{ width: 320 }}
                    placeholder="选择 VPC（不选则查全部）"
                    allowClear
                    value={vswitchVpcId}
                    onChange={setVswitchVpcId}
                    options={vpcs.map((v) => ({ value: v.id, label: `${v.name}（${v.id}）` }))}
                  />
                  <Button
                    type="primary"
                    icon={<PlusOutlined />}
                    onClick={openVSwitchModal}
                    disabled={vpcs.length === 0}
                  >
                    新建交换机
                  </Button>
                </Space>
                <Table<AliVSwitch>
                  rowKey="id"
                  columns={vswitchColumns}
                  dataSource={vswitches}
                  loading={loading}
                  pagination={{ showTotal: (t) => `共 ${t} 个交换机` }}
                  locale={{ emptyText: '暂无交换机，点击「新建交换机」创建' }}
                />
              </>
            ),
          },
        ]}
      />
      <Modal title="新建 VPC" open={vpcOpen} onCancel={() => setVpcOpen(false)} onOk={onCreateVpc} destroyOnClose>
        <Form<VpcFormValues> form={vpcForm} layout="vertical">
          <Form.Item name="name" label="VPC 名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：my-vpc" />
          </Form.Item>
          <Form.Item
            name="cidr"
            label="CIDR 网段"
            rules={[{ required: true, message: '请输入 CIDR' }]}
            extra="推荐使用 10.0.0.0/8、172.16.0.0/12 或 192.168.0.0/16"
          >
            <Input placeholder="如：10.0.0.0/8" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input placeholder="VPC 用途说明" />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="新建交换机"
        open={vswitchOpen}
        onCancel={() => setVswitchOpen(false)}
        onOk={onCreateVSwitch}
        destroyOnClose
      >
        <Form<VSwitchFormValues> form={vswitchForm} layout="vertical">
          <Form.Item name="vpc_id" label="所属 VPC" rules={[{ required: true, message: '请选择 VPC' }]}>
            <Select
              placeholder="选择 VPC"
              options={vpcs.map((v) => ({ value: v.id, label: `${v.name}（${v.id}）` }))}
            />
          </Form.Item>
          <Form.Item
            name="zone_id"
            label="可用区"
            rules={[{ required: true, message: '请输入可用区' }]}
            extra="如 cn-hangzhou-h，需与地域对应"
          >
            <Input placeholder="如：cn-hangzhou-h" />
          </Form.Item>
          <Form.Item
            name="cidr"
            label="CIDR 网段"
            rules={[{ required: true, message: '请输入 CIDR' }]}
            extra="必须在所属 VPC 的网段范围内，如 10.0.1.0/24"
          >
            <Input placeholder="如：10.0.1.0/24" />
          </Form.Item>
          <Form.Item name="name" label="交换机名称">
            <Input placeholder="可选，如：web-vswitch" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input placeholder="可选，交换机用途说明" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
