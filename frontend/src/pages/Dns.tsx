import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from 'antd';
import { CloudUploadOutlined, DownloadOutlined, PlusOutlined, SearchOutlined, SettingOutlined, SyncOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  createDnsRecord,
  deleteDnsRecord,
  getCloudflareStatus,
  listDnsRecords,
  pullDnsRecords,
  saveCloudflareToken,
  syncDnsRecord,
  updateDnsRecord,
  type DnsRecordDto,
} from '../api/dns';

const TYPE_COLOR: Record<DnsRecordDto['type'], string> = {
  A: 'blue',
  AAAA: 'purple',
  CNAME: 'green',
  TXT: 'orange',
};

interface DnsFormValues {
  zone_name: string;
  name: string;
  type: DnsRecordDto['type'];
  content: string;
  ttl: number;
  proxied: boolean;
}

/** DNS 解析页：Cloudflare DNS 记录（真实接口）+ 同步 + Token 配置 */
export default function Dns() {
  const [list, setList] = useState<DnsRecordDto[]>([]);
  const [loading, setLoading] = useState(false);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [keyword, setKeyword] = useState('');
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<DnsRecordDto | null>(null);
  const [tokenOpen, setTokenOpen] = useState(false);
  const [pullOpen, setPullOpen] = useState(false);
  const [syncing, setSyncing] = useState<number | null>(null);
  const [form] = Form.useForm<DnsFormValues>();
  const [tokenForm] = Form.useForm<{ api_token: string }>();
  const [pullForm] = Form.useForm<{ zone_name: string }>();

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [records, status] = await Promise.all([listDnsRecords(), getCloudflareStatus()]);
      setList(records);
      setConfigured(status.configured);
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
        (r) =>
          !keyword ||
          r.name.includes(keyword) ||
          r.content.includes(keyword) ||
          r.zone_name.includes(keyword),
      ),
    [list, keyword],
  );

  const openModal = (r?: DnsRecordDto) => {
    setEditing(r ?? null);
    form.setFieldsValue(
      r ?? ({ type: 'A', ttl: 300, proxied: false } as DnsFormValues),
    );
    setOpen(true);
  };

  const onFinish = async (values: DnsFormValues) => {
    try {
      const res = editing
        ? await updateDnsRecord(editing.id, values)
        : await createDnsRecord(values);
      message.success(res.note ?? (editing ? 'DNS 记录已更新' : 'DNS 记录已添加'));
      setOpen(false);
      form.resetFields();
      fetchAll();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const doSync = async (id: number) => {
    setSyncing(id);
    try {
      const res = await syncDnsRecord(id);
      message.success(res.note ?? '已同步到 Cloudflare');
      fetchAll();
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      setSyncing(null);
    }
  };

  const doPull = async (values: { zone_name: string }) => {
    try {
      const res = await pullDnsRecords(values.zone_name.trim());
      message.success(`拉取完成：远端 ${res.pulled} 条，新增 ${res.created} 条，更新 ${res.updated} 条`);
      setPullOpen(false);
      pullForm.resetFields();
      fetchAll();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const doSaveToken = async (values: { api_token: string }) => {
    try {
      await saveCloudflareToken(values.api_token.trim());
      message.success('Token 已保存（加密存储）');
      setTokenOpen(false);
      tokenForm.resetFields();
      setConfigured(true);
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const remove = async (id: number) => {
    try {
      await deleteDnsRecord(id);
      message.success('记录已删除');
      fetchAll();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const columns: ColumnsType<DnsRecordDto> = [
    { title: '域名', dataIndex: 'name', key: 'name', width: 220, ellipsis: true },
    { title: 'Zone', dataIndex: 'zone_name', key: 'zone_name', width: 160 },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 90,
      render: (v: DnsRecordDto['type']) => <Tag color={TYPE_COLOR[v] ?? 'default'}>{v}</Tag>,
    },
    { title: '记录值', dataIndex: 'content', key: 'content', ellipsis: true },
    { title: 'TTL', dataIndex: 'ttl', key: 'ttl', width: 90, render: (v: number) => (v === 1 ? '自动' : v) },
    {
      title: 'CDN 代理',
      dataIndex: 'proxied',
      key: 'proxied',
      width: 90,
      render: (v: boolean) => (v ? <Tag color="orange">开启</Tag> : <Tag>关闭</Tag>),
    },
    {
      title: '同步状态',
      key: 'sync',
      width: 110,
      render: (_, r) =>
        r.cf_record_id ? <Tag color="success">已同步</Tag> : <Tag color="default">未同步</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 210,
      fixed: 'right',
      render: (_, record) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<SyncOutlined />}
            loading={syncing === record.id}
            onClick={() => doSync(record.id)}
          >
            同步
          </Button>
          <Button type="link" size="small" onClick={() => openModal(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除这条 DNS 记录吗？（将同时尝试删除 Cloudflare 远端记录）" onConfirm={() => remove(record.id)}>
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
      title="DNS 解析（Cloudflare）"
      extra={
        <Space wrap>
          <Button icon={<SettingOutlined />} onClick={() => setTokenOpen(true)}>
            Token 配置
            {configured === false && <Tag color="warning" style={{ marginLeft: 4 }}>未配置</Tag>}
            {configured === true && <Tag color="success" style={{ marginLeft: 4 }}>已配置</Tag>}
          </Button>
          <Button icon={<DownloadOutlined />} onClick={() => setPullOpen(true)}>
            从 Cloudflare 拉取
          </Button>
          <Button icon={<CloudUploadOutlined />} onClick={fetchAll}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>
            新建记录
          </Button>
        </Space>
      }
    >
      {configured === false && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="尚未配置 Cloudflare API Token"
          description="记录只能保存在本地，无法同步到 Cloudflare。点击右上角「Token 配置」填写 Token（需要 Zone.DNS 编辑权限）。"
        />
      )}
      <Input
        placeholder="搜索域名 / Zone / 记录值"
        prefix={<SearchOutlined />}
        allowClear
        style={{ width: 280, marginBottom: 16 }}
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
      />
      <Table<DnsRecordDto>
        rowKey="id"
        columns={columns}
        dataSource={filtered}
        loading={loading}
        scroll={{ x: 1100 }}
        pagination={{ showSizeChanger: true, showTotal: (t) => `共 ${t} 条记录` }}
      />

      {/* 新建 / 编辑 */}
      <Modal
        title={editing ? '编辑 DNS 记录' : '新建 DNS 记录'}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        destroyOnClose
      >
        <Form<DnsFormValues> form={form} layout="vertical" onFinish={onFinish}>
          <Form.Item name="zone_name" label="Zone（根域名）" rules={[{ required: true, message: '请输入 zone' }]} tooltip="如 example.com，需已接入 Cloudflare">
            <Input placeholder="如：example.com" />
          </Form.Item>
          <Form.Item name="name" label="记录名（完整域名）" rules={[{ required: true, message: '请输入记录名' }]}>
            <Input placeholder="如：panel.example.com" />
          </Form.Item>
          <Form.Item name="type" label="记录类型" rules={[{ required: true }]}>
            <Select options={(['A', 'AAAA', 'CNAME', 'TXT'] as const).map((t) => ({ label: t, value: t }))} />
          </Form.Item>
          <Form.Item name="content" label="记录值" rules={[{ required: true, message: '请输入记录值' }]}>
            <Input placeholder="IP 或目标域名" />
          </Form.Item>
          <Space style={{ display: 'flex' }} size={16}>
            <Form.Item name="ttl" label="TTL（秒，1=自动）" rules={[{ required: true }]} style={{ flex: 1 }}>
              <InputNumber min={1} max={86400} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="proxied" label="CDN 代理" valuePropName="checked" style={{ flex: 1 }}>
              <Switch />
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      {/* Token 配置 */}
      <Modal
        title="Cloudflare API Token"
        open={tokenOpen}
        onCancel={() => setTokenOpen(false)}
        onOk={() => tokenForm.submit()}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="Token 权限要求"
          description="在 Cloudflare 控制台创建 API Token，模板选择「编辑区域 DNS」或自定义授予 Zone.DNS 编辑权限。Token 加密存储在本地数据库，不会回显。"
        />
        <Form<{ api_token: string }> form={tokenForm} layout="vertical" onFinish={doSaveToken}>
          <Form.Item name="api_token" label="API Token" rules={[{ required: true, message: '请输入 Token' }]}>
            <Input.Password placeholder="粘贴 Cloudflare API Token" autoComplete="off" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 从远端拉取 */}
      <Modal
        title="从 Cloudflare 拉取记录"
        open={pullOpen}
        onCancel={() => setPullOpen(false)}
        onOk={() => pullForm.submit()}
        destroyOnClose
      >
        <Form<{ zone_name: string }> form={pullForm} layout="vertical" onFinish={doPull}>
          <Form.Item name="zone_name" label="Zone（根域名）" rules={[{ required: true, message: '请输入 zone' }]}>
            <Input placeholder="如：example.com" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
