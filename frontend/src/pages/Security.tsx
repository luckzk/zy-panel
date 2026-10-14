import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Radio,
  Select,
  Space,
  Table,
  Tag,
  message,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { listTenants, type TenantOption } from '../api/tenants';
import {
  addSecurityRule,
  deleteSecurityRule,
  listSecurityRules,
  listVcns,
  openAllPorts,
  type SecurityRuleInfo,
  type VcnInfo,
} from '../api/security';

interface RuleFormValues {
  direction: 'ingress' | 'egress';
  protocol: string;
  ports: string;
  source: string;
  description: string;
}

/** 安全组页：租户/VCN 选择 + 真实安全列表规则 + 新增/删除 */
export default function Security() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number>();
  const [compartmentId, setCompartmentId] = useState('');
  const [vcns, setVcns] = useState<VcnInfo[]>([]);
  const [vcnId, setVcnId] = useState<string>();
  const [list, setList] = useState<SecurityRuleInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [tenantsLoaded, setTenantsLoaded] = useState(false);
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm<RuleFormValues>();

  const fetchVcns = useCallback(async (tid: number, comp: string) => {
    try {
      const vs = await listVcns(tid, comp.trim() || undefined);
      setVcns(vs);
      setVcnId(vs.length > 0 ? vs[0].id : undefined);
    } catch {
      setVcns([]);
      setVcnId(undefined);
    }
  }, []);

  const fetchRules = useCallback(async (tid: number, vid: string, comp: string) => {
    setLoading(true);
    try {
      setList(await listSecurityRules(tid, vid, comp.trim() || undefined));
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
    if (tenantId !== undefined) fetchVcns(tenantId, compartmentId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  useEffect(() => {
    if (tenantId !== undefined && vcnId) fetchRules(tenantId, vcnId, compartmentId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vcnId]);

  const refresh = () => {
    if (tenantId !== undefined) {
      if (vcnId) fetchRules(tenantId, vcnId, compartmentId);
      else fetchVcns(tenantId, compartmentId);
    }
  };

  /** 一键放行常用端口（真实接口：缺哪个补哪个） */
  const openCommonPorts = async () => {
    if (tenantId === undefined) return;
    const first = list.find((r) => r.direction === 'ingress');
    if (!first) {
      message.warning('当前 VCN 下没有可用的安全列表');
      return;
    }
    const exists = (ports: string) => list.some((r) => r.direction === 'ingress' && r.ports === ports);
    const targets = [
      { ports: '80', description: 'HTTP' },
      { ports: '443', description: 'HTTPS' },
      { ports: '22', description: 'SSH' },
    ].filter((t) => !exists(t.ports));
    if (targets.length === 0) {
      message.info('常用端口已全部放行');
      return;
    }
    try {
      for (const t of targets) {
        await addSecurityRule(tenantId, {
          security_list_id: first.securityListId,
          direction: 'ingress',
          protocol: 'TCP',
          port_range: t.ports,
          cidr: '0.0.0.0/0',
          description: t.description,
        });
      }
      message.success(`已放行 ${targets.map((t) => t.ports).join('、')}`);
      refresh();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  /** 一键放行所有端口：危险操作，二次确认后调用真实接口 */
  const confirmOpenAllPorts = () => {
    if (tenantId === undefined) return;
    const first = list.find((r) => r.direction === 'ingress');
    if (!first) {
      message.warning('当前 VCN 下没有可用的安全列表');
      return;
    }
    Modal.confirm({
      title: '确认放行所有端口？',
      content: (
        <div>
          <p>
            将向安全列表 <b>{first.securityListName || first.securityListId}</b> 追加{' '}
            <b>0.0.0.0/0</b> 与 <b>::/0</b> 的全协议入站规则，
            该实例的所有端口将直接暴露到公网。
          </p>
          <p style={{ color: '#faad14' }}>请确认实例系统防火墙已配置好，否则有被扫描入侵的风险。</p>
        </div>
      ),
      okText: '确认放行',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const res = await openAllPorts(tenantId, first.securityListId);
          if (res.added.length > 0) {
            message.success(`已放行所有端口（新增 ${res.added.join('、')}）`);
          } else {
            message.info('已处于全放行状态，无需重复操作');
          }
          refresh();
        } catch {
          /* 错误已由拦截器提示 */
        }
      },
    });
  };

  const onFinish = async (values: RuleFormValues) => {
    if (tenantId === undefined) return;
    const first = list.find((r) => r.direction === values.direction);
    if (!first) {
      message.warning('当前 VCN 下没有可用的安全列表');
      return;
    }
    try {
      await addSecurityRule(tenantId, {
        security_list_id: first.securityListId,
        direction: values.direction,
        protocol: values.protocol,
        port_range: values.ports,
        cidr: values.source,
        description: values.description || '',
      });
      message.success('规则已添加');
      setOpen(false);
      form.resetFields();
      refresh();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const remove = async (id: string) => {
    if (tenantId === undefined) return;
    try {
      await deleteSecurityRule(tenantId, id);
      message.success('规则已删除');
      refresh();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const columns: ColumnsType<SecurityRuleInfo> = [
    { title: '安全列表', dataIndex: 'securityListName', key: 'securityListName', width: 150, ellipsis: true },
    {
      title: '方向',
      dataIndex: 'direction',
      key: 'direction',
      width: 90,
      render: (v: SecurityRuleInfo['direction']) =>
        v === 'ingress' ? <Tag color="blue">入站</Tag> : <Tag color="green">出站</Tag>,
    },
    { title: '协议', dataIndex: 'protocol', key: 'protocol', width: 90 },
    { title: '端口范围', dataIndex: 'ports', key: 'ports', width: 120 },
    { title: '来源/目标', dataIndex: 'source', key: 'source', width: 170 },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_, record) => (
        <Popconfirm title="确定删除这条规则吗？" onConfirm={() => remove(record.id)}>
          <Button type="link" size="small" danger>
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  if (tenantsLoaded && tenants.length === 0) {
    return (
      <Card title="安全组规则">
        <Empty description="还没有租户配置，请先添加 OCI 租户">
          <Link to="/tenants">
            <Button type="primary">去添加租户</Button>
          </Link>
        </Empty>
      </Card>
    );
  }

  return (
    <Card
      title="安全组规则"
      extra={
        <Space>
          <Button onClick={openCommonPorts}>一键放行常用端口</Button>
          <Button danger onClick={confirmOpenAllPorts}>
            放行所有端口
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
            添加规则
          </Button>
        </Space>
      }
    >
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          style={{ width: 240 }}
          placeholder="选择租户"
          value={tenantId}
          onChange={setTenantId}
          options={tenants.map((t) => ({ value: t.id, label: `${t.name}（${t.region}）` }))}
        />
        <Input
          style={{ width: 300 }}
          placeholder="Compartment OCID（默认租户根 compartment）"
          value={compartmentId}
          onChange={(e) => setCompartmentId(e.target.value)}
          allowClear
        />
        <Select
          style={{ width: 280 }}
          placeholder="选择 VCN"
          value={vcnId}
          onChange={setVcnId}
          options={vcns.map((v) => ({ value: v.id, label: `${v.name}（${v.cidr}）` }))}
        />
        <Button type="primary" loading={loading} onClick={refresh}>
          查询
        </Button>
      </Space>
      <Table<SecurityRuleInfo>
        rowKey="id"
        columns={columns}
        dataSource={list}
        loading={loading}
        pagination={{ showTotal: (t) => `共 ${t} 条规则` }}
      />
      <Modal title="添加安全组规则" open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnClose>
        <Form<RuleFormValues> form={form} layout="vertical" onFinish={onFinish} initialValues={{ direction: 'ingress', protocol: 'TCP' }}>
          <Form.Item name="direction" label="方向" rules={[{ required: true }]} extra="将添加到当前 VCN 下第一个匹配方向的安全列表">
            <Radio.Group options={[{ label: '入站', value: 'ingress' }, { label: '出站', value: 'egress' }]} />
          </Form.Item>
          <Form.Item name="protocol" label="协议" rules={[{ required: true }]}>
            <Select options={['TCP', 'UDP', 'ICMP', '全部'].map((p) => ({ label: p, value: p }))} />
          </Form.Item>
          <Form.Item name="ports" label="端口范围" rules={[{ required: true, message: '请输入端口，如 80、8000-9000 或 all' }]}>
            <Input placeholder="如：80、443、8000-9000、all" />
          </Form.Item>
          <Form.Item name="source" label="来源/目标 CIDR" rules={[{ required: true, message: '请输入 CIDR' }]}>
            <Input placeholder="如：0.0.0.0/0" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input placeholder="规则用途说明" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
