import { useCallback, useEffect, useState } from 'react';
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
import { listTenants, listTenantRegions, type TenantOption } from '../api/tenants';
import {
  addAliSgRule,
  createAliSecurityGroup,
  deleteAliSecurityGroup,
  deleteAliSgRule,
  listAliSecurityGroups,
  listAliSgRules,
  type AliSecurityGroup,
  type AliSgRule,
} from '../api/aliyun';

interface RuleFormValues {
  direction: 'ingress' | 'egress';
  protocol: string;
  port_range: string;
  cidr: string;
  description: string;
}

const PROTOCOL_OPTIONS = ['tcp', 'udp', 'icmp', 'all'];

/** 阿里云安全组：安全组选择 + 规则增删 + 新建/删除安全组 */
export default function AliyunSecurityGroups() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number>();
  const [regions, setRegions] = useState<{ value: string; label: string }[]>([]);
  const [regionId, setRegionId] = useState<string>();
  const [groups, setGroups] = useState<AliSecurityGroup[]>([]);
  const [sgId, setSgId] = useState<string>();
  const [rules, setRules] = useState<AliSgRule[]>([]);
  const [loading, setLoading] = useState(false);
  const [tenantsLoaded, setTenantsLoaded] = useState(false);
  const [ruleOpen, setRuleOpen] = useState(false);
  const [sgOpen, setSgOpen] = useState(false);
  const [ruleForm] = Form.useForm<RuleFormValues>();
  const [sgForm] = Form.useForm<{ name: string; description: string }>();

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

  const fetchGroups = useCallback(
    async (tid: number, region?: string) => {
      setLoading(true);
      try {
        const gs = await listAliSecurityGroups(tid, region);
        setGroups(gs);
        setSgId((cur) => (gs.some((g) => g.id === cur) ? cur : gs[0]?.id));
      } catch {
        setGroups([]);
        message.error('安全组查询失败');
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  const fetchRules = useCallback(async (tid: number, sg: string, region?: string) => {
    setLoading(true);
    try {
      setRules(await listAliSgRules(tid, sg, region));
    } catch {
      setRules([]);
      message.error('规则查询失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tenantId !== undefined) fetchGroups(tenantId, regionId);
  }, [tenantId, regionId, fetchGroups]);

  useEffect(() => {
    if (tenantId !== undefined && sgId) fetchRules(tenantId, sgId, regionId);
    else setRules([]);
  }, [tenantId, sgId, regionId, fetchRules]);

  const refresh = () => {
    if (tenantId !== undefined) fetchGroups(tenantId, regionId);
  };

  const onAddRule = async () => {
    if (tenantId === undefined || !sgId) return;
    const v = await ruleForm.validateFields();
    // 阿里云端口格式为 起/止（如 80/80、1/65535），兼容用户输入 80 或 8000-9000
    let portRange = v.port_range.trim();
    if (v.protocol === 'all') portRange = '-1/-1';
    else if (/^all$/i.test(portRange)) portRange = '-1/-1';
    else if (/^\d+$/.test(portRange)) portRange = `${portRange}/${portRange}`;
    else if (/^(\d+)-(\d+)$/.test(portRange)) portRange = portRange.replace('-', '/');
    await addAliSgRule(
      tenantId,
      sgId,
      {
        direction: v.direction,
        protocol: v.protocol,
        port_range: portRange,
        cidr: v.cidr.trim() || '0.0.0.0/0',
        description: v.description?.trim() || '',
      },
      regionId,
    );
    message.success('规则已添加');
    setRuleOpen(false);
    fetchRules(tenantId, sgId, regionId);
  };

  const onDeleteRule = async (r: AliSgRule) => {
    if (tenantId === undefined || !sgId) return;
    await deleteAliSgRule(
      tenantId,
      sgId,
      { direction: r.direction, protocol: r.protocol, port_range: r.port_range, cidr: r.cidr },
      regionId,
    );
    message.success('规则已删除');
    fetchRules(tenantId, sgId, regionId);
  };

  const onCreateSg = async () => {
    if (tenantId === undefined) return;
    const v = await sgForm.validateFields();
    const r = await createAliSecurityGroup(
      tenantId,
      { name: v.name.trim(), description: v.description?.trim() || '' },
      regionId,
    );
    message.success(`安全组已创建：${r.security_group_id}`);
    setSgOpen(false);
    fetchGroups(tenantId, regionId);
  };

  const onDeleteSg = async () => {
    if (tenantId === undefined || !sgId) return;
    await deleteAliSecurityGroup(tenantId, sgId, regionId);
    message.success('安全组已删除');
    setSgId(undefined);
    fetchGroups(tenantId, regionId);
  };

  /** 一键放行常用端口（80/443/22 入站，未放行的才加） */
  const openCommonPorts = async () => {
    if (tenantId === undefined || !sgId) {
      message.warning('请先选择安全组');
      return;
    }
    const exists = (p: string) =>
      rules.some((r) => r.direction === 'ingress' && r.protocol === 'tcp' && r.port_range === `${p}/${p}`);
    const targets = [
      { port: '80', description: 'HTTP' },
      { port: '443', description: 'HTTPS' },
      { port: '22', description: 'SSH' },
    ].filter((t) => !exists(t.port));
    if (targets.length === 0) {
      message.info('常用端口已全部放行');
      return;
    }
    try {
      for (const t of targets) {
        await addAliSgRule(
          tenantId,
          sgId,
          { direction: 'ingress', protocol: 'tcp', port_range: `${t.port}/${t.port}`, cidr: '0.0.0.0/0', description: t.description },
          regionId,
        );
      }
      message.success(`已放行：${targets.map((t) => t.port).join('、')}`);
      fetchRules(tenantId, sgId, regionId);
    } catch {
      message.error('放行失败');
    }
  };

  const columns: ColumnsType<AliSgRule> = [
    {
      title: '方向',
      dataIndex: 'direction',
      key: 'direction',
      width: 90,
      render: (v: string) => (
        <Tag color={v === 'ingress' ? 'blue' : 'orange'}>{v === 'ingress' ? '入站' : '出站'}</Tag>
      ),
    },
    { title: '协议', dataIndex: 'protocol', key: 'protocol', width: 90, render: (v: string) => v.toUpperCase() },
    { title: '端口范围', dataIndex: 'port_range', key: 'port_range', width: 130 },
    { title: '来源/目标', dataIndex: 'cidr', key: 'cidr', width: 160 },
    { title: '策略', dataIndex: 'policy', key: 'policy', width: 90, render: (v: string) => v || 'accept' },
    { title: '优先级', dataIndex: 'priority', key: 'priority', width: 90 },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, r) => (
        <Popconfirm title="确定删除这条规则吗？" onConfirm={() => onDeleteRule(r)}>
          <Button size="small" danger>
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  if (tenantsLoaded && tenants.length === 0) {
    return (
      <Card title="安全组">
        <Empty description="还没有阿里云租户，请先添加" />
      </Card>
    );
  }

  return (
    <Card
      title="安全组"
      extra={
        <Space>
          <Button onClick={openCommonPorts}>一键放行常用端口</Button>
          <Button icon={<PlusOutlined />} onClick={() => setSgOpen(true)}>
            新建安全组
          </Button>
          {sgId && (
            <Popconfirm title="确定删除当前安全组吗？" onConfirm={onDeleteSg}>
              <Button danger>删除安全组</Button>
            </Popconfirm>
          )}
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setRuleOpen(true)} disabled={!sgId}>
            添加规则
          </Button>
        </Space>
      }
    >
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
        <Select
          style={{ width: 300 }}
          placeholder="选择安全组"
          value={sgId}
          onChange={setSgId}
          options={groups.map((g) => ({ value: g.id, label: `${g.name}（${g.id}）` }))}
          loading={loading}
        />
        <Button onClick={refresh} loading={loading}>
          刷新
        </Button>
      </Space>
      <Table<AliSgRule>
        rowKey={(r) => `${r.direction}-${r.protocol}-${r.port_range}-${r.cidr}`}
        columns={columns}
        dataSource={rules}
        loading={loading}
        pagination={{ showTotal: (t) => `共 ${t} 条规则` }}
        locale={{ emptyText: sgId ? '该安全组暂无规则' : '请先选择安全组' }}
      />
      <Modal title="添加安全组规则" open={ruleOpen} onCancel={() => setRuleOpen(false)} onOk={onAddRule} destroyOnClose>
        <Form<RuleFormValues>
          form={ruleForm}
          layout="vertical"
          initialValues={{ direction: 'ingress', protocol: 'tcp', cidr: '0.0.0.0/0' }}
        >
          <Form.Item name="direction" label="方向" rules={[{ required: true }]}>
            <Radio.Group options={[{ label: '入站', value: 'ingress' }, { label: '出站', value: 'egress' }]} />
          </Form.Item>
          <Form.Item name="protocol" label="协议" rules={[{ required: true }]}>
            <Select options={PROTOCOL_OPTIONS.map((p) => ({ label: p.toUpperCase(), value: p }))} />
          </Form.Item>
          <Form.Item
            name="port_range"
            label="端口范围"
            rules={[{ required: true, message: '请输入端口，如 80、8000-9000 或 all' }]}
            extra="阿里云格式为 起/止（如 80/80）；输入 80 或 8000-9000 会自动转换，all 转为 -1/-1"
          >
            <Input placeholder="如：80、8000-9000、all" />
          </Form.Item>
          <Form.Item name="cidr" label="来源/目标 CIDR" rules={[{ required: true, message: '请输入 CIDR' }]}>
            <Input placeholder="如：0.0.0.0/0" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input placeholder="规则用途说明" />
          </Form.Item>
        </Form>
      </Modal>
      <Modal title="新建安全组" open={sgOpen} onCancel={() => setSgOpen(false)} onOk={onCreateSg} destroyOnClose>
        <Form form={sgForm} layout="vertical">
          <Form.Item name="name" label="安全组名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：web-sg" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input placeholder="安全组用途说明" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
