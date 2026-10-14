import { useCallback, useEffect, useState } from 'react';
import {
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
  Typography,
  message,
} from 'antd';
import { BellOutlined, PlusOutlined, SendOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  createNotification,
  deleteNotification,
  listNotifications,
  testNotification,
  updateNotification,
  type NotificationChannel,
  type NotificationType,
  type TestSendResult,
} from '../api/notifications';
import { getTgBotConfig, updateTgBotConfig } from '../api/system';

const { Text } = Typography;

const TYPE_META: Record<NotificationType, { color: string; text: string }> = {
  telegram: { color: 'blue', text: 'Telegram' },
  email: { color: 'orange', text: '邮件' },
};

interface ChannelFormValues {
  name: string;
  type: NotificationType;
  enabled: boolean;
  bot_token?: string;
  chat_id?: string;
  smtp_host?: string;
  smtp_port?: number;
  smtp_user?: string;
  smtp_pass?: string;
  from_addr?: string;
  to_addrs?: string;
}

/** 测试发送结果弹窗 */
function TestResultModal({ result, open, onClose }: { result: TestSendResult | null; open: boolean; onClose: () => void }) {
  return (
    <Modal title="测试发送结果" open={open} onCancel={onClose} footer={<Button onClick={onClose}>关闭</Button>}>
      {result && (
        <Space direction="vertical" style={{ width: '100%' }}>
          <div>
            发送{result.ok ? '成功' : '失败'}
            {result.name ? `（${result.name}）` : ''}
          </div>
          <div style={{ color: result.ok ? '#52c41a' : '#ff4d4f', wordBreak: 'break-all' }}>{result.msg}</div>
        </Space>
      )}
    </Modal>
  );
}

/** 通知渠道配置页：Telegram / 邮件渠道的 CRUD + 测试发送 */
export default function Notifications() {
  const [list, setList] = useState<NotificationChannel[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<NotificationChannel | null>(null);
  const [testLoadingId, setTestLoadingId] = useState<number | null>(null);
  const [testResult, setTestResult] = useState<TestSendResult | null>(null);
  const [testResultOpen, setTestResultOpen] = useState(false);
  const [form] = Form.useForm<ChannelFormValues>();
  const channelType = Form.useWatch('type', form);
  // TG 机器人操作
  const [botEnabled, setBotEnabled] = useState(false);
  const [botChatIds, setBotChatIds] = useState('');
  const [botHasToken, setBotHasToken] = useState(false);
  const [botSaving, setBotSaving] = useState(false);

  const fetchBot = useCallback(async () => {
    try {
      const cfg = await getTgBotConfig();
      setBotEnabled(cfg.enabled);
      setBotChatIds((cfg.chat_ids ?? []).join(','));
      setBotHasToken(!!cfg.token);
    } catch {
      /* 无管理员权限时接口 403，静默 */
    }
  }, []);

  const saveBot = async () => {
    setBotSaving(true);
    try {
      await updateTgBotConfig(botEnabled, botChatIds);
      message.success('TG 机器人配置已保存');
      fetchBot();
    } finally {
      setBotSaving(false);
    }
  };

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      setList(await listNotifications());
    } catch {
      setList([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    fetchBot();
  }, [fetchAll, fetchBot]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ type: 'telegram', enabled: true, smtp_port: 587 });
    setOpen(true);
  };

  const openEdit = (record: NotificationChannel) => {
    setEditing(record);
    form.resetFields();
    // 敏感字段留空表示不改（后端浅合并）
    const cfg = record.config ?? {};
    form.setFieldsValue({
      name: record.name,
      type: record.type,
      enabled: record.enabled,
      bot_token: '',
      chat_id: cfg.chat_id ?? '',
      smtp_host: cfg.smtp_host ?? '',
      smtp_port: cfg.smtp_port ? Number(cfg.smtp_port) : 587,
      smtp_user: cfg.smtp_user ?? '',
      smtp_pass: '',
      from_addr: cfg.from_addr ?? '',
      to_addrs: Array.isArray(cfg.to_addrs) ? (cfg.to_addrs as string[]).join('\n') : (cfg.to_addrs ?? ''),
    });
    setOpen(true);
  };

  /** 表单值 → 后端 config_json；编辑时敏感字段留空则不传 */
  const buildConfigJson = (values: ChannelFormValues): Record<string, unknown> => {
    if (values.type === 'telegram') {
      const cfg: Record<string, unknown> = { chat_id: values.chat_id?.trim() };
      if (values.bot_token?.trim()) cfg.bot_token = values.bot_token.trim();
      return cfg;
    }
    const addrs = (values.to_addrs ?? '').split('\n').map((s) => s.trim()).filter(Boolean);
    const cfg: Record<string, unknown> = {
      smtp_host: values.smtp_host?.trim(),
      smtp_port: values.smtp_port ?? 587,
      smtp_user: values.smtp_user?.trim(),
      to_addrs: addrs,
    };
    if (values.from_addr?.trim()) cfg.from_addr = values.from_addr.trim();
    if (values.smtp_pass?.trim()) cfg.smtp_pass = values.smtp_pass.trim();
    return cfg;
  };

  const onFinish = async (values: ChannelFormValues) => {
    try {
      if (editing) {
        await updateNotification(editing.id, {
          name: values.name,
          enabled: values.enabled,
          config_json: buildConfigJson(values),
        });
        message.success('渠道已更新');
      } else {
        await createNotification({
          type: values.type,
          name: values.name,
          enabled: values.enabled,
          config_json: buildConfigJson(values),
        });
        message.success('渠道已创建');
      }
      setOpen(false);
      fetchAll();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const toggleEnabled = async (record: NotificationChannel, enabled: boolean) => {
    try {
      await updateNotification(record.id, { enabled });
      message.success(enabled ? '渠道已启用' : '渠道已停用');
      fetchAll();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const doTest = async (record: NotificationChannel) => {
    setTestLoadingId(record.id);
    try {
      const result = await testNotification(record.id);
      setTestResult(result);
      setTestResultOpen(true);
      if (result.ok) message.success('测试消息发送成功');
      else message.error('测试消息发送失败');
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      setTestLoadingId(null);
    }
  };

  const doDelete = async (record: NotificationChannel) => {
    try {
      await deleteNotification(record.id);
      message.success('渠道已删除');
      fetchAll();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const isTelegram = (channelType ?? editing?.type ?? 'telegram') === 'telegram';

  const columns: ColumnsType<NotificationChannel> = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 180, render: (v: string) => v || '-' },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 110,
      render: (v: NotificationType) => <Tag color={TYPE_META[v]?.color}>{TYPE_META[v]?.text ?? v}</Tag>,
    },
    {
      title: '关键配置',
      key: 'config',
      ellipsis: true,
      render: (_, r) => {
        const cfg = r.config ?? {};
        if (r.type === 'telegram') return <span>chat_id: {cfg.chat_id ?? '-'}</span>;
        return (
          <span>
            {cfg.smtp_host ?? '-'}:{cfg.smtp_port ?? '-'} →{' '}
            {Array.isArray(cfg.to_addrs) ? (cfg.to_addrs as string[]).join(', ') : (cfg.to_addrs ?? '-')}
          </span>
        );
      },
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 90,
      render: (v: boolean, r) => <Switch checked={v} onChange={(checked) => toggleEnabled(r, checked)} />,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (v: string | null) => (v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 240,
      render: (_, record) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<SendOutlined />}
            loading={testLoadingId === record.id}
            onClick={() => doTest(record)}
          >
            测试发送
          </Button>
          <Button type="link" size="small" onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除该渠道吗？" onConfirm={() => doDelete(record)}>
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Card title="TG 机器人操作" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Text type="secondary" style={{ fontSize: 12 }}>
            启用后，可在 Telegram 里直接给机器人发命令查实例、管抢机、换 IP。
            Token 复用下方第一个启用的 Telegram 渠道{botHasToken ? '（已配置）' : '（尚未配置 Telegram 渠道）'}。
            支持命令：/instances /instance /snatch /traffic /startvm /stopvm /rebootvm /changeip。
          </Text>
          <Space wrap>
            <Space>
              <Text>启用机器人操作</Text>
              <Switch checked={botEnabled} onChange={setBotEnabled} />
            </Space>
            <Input
              placeholder="白名单 chat_id，逗号分隔；留空则响应所有人"
              value={botChatIds}
              onChange={(e) => setBotChatIds(e.target.value)}
              style={{ width: 320 }}
            />
            <Button type="primary" loading={botSaving} onClick={saveBot}>
              保存
            </Button>
          </Space>
        </Space>
      </Card>
      <Card
      title={
        <Space>
          <BellOutlined />
          通知渠道
        </Space>
      }
      extra={
        <Space>
          <Button onClick={fetchAll}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建渠道
          </Button>
        </Space>
      }
    >
      <Table<NotificationChannel>
        rowKey="id"
        columns={columns}
        dataSource={list}
        loading={loading}
        scroll={{ x: 1000 }}
        pagination={{ showSizeChanger: true, showTotal: (t) => `共 ${t} 个渠道` }}
      />
      <Modal
        title={editing ? '编辑通知渠道' : '新建通知渠道'}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        destroyOnClose
        width={560}
      >
        <Form<ChannelFormValues> form={form} layout="vertical" onFinish={onFinish} initialValues={{ enabled: true }}>
          <Form.Item name="name" label="渠道名称">
            <Input placeholder="如：运维 TG 群、告警邮箱" />
          </Form.Item>
          <Form.Item name="type" label="渠道类型" rules={[{ required: true }]}>
            <Select
              disabled={!!editing}
              options={[
                { label: 'Telegram', value: 'telegram' },
                { label: '邮件', value: 'email' },
              ]}
            />
          </Form.Item>
          {isTelegram ? (
            <>
              <Form.Item
                name="bot_token"
                label={editing ? 'Bot Token（留空表示不改）' : 'Bot Token'}
                rules={editing ? [] : [{ required: true, message: '请输入 Bot Token' }]}
                tooltip="找 @BotFather 创建机器人后获取"
              >
                <Input.Password placeholder="123456:ABC-DEF..." autoComplete="new-password" />
              </Form.Item>
              <Form.Item name="chat_id" label="Chat ID" rules={[{ required: true, message: '请输入 Chat ID' }]}>
                <Input placeholder="群组或个人聊天的 chat_id" />
              </Form.Item>
            </>
          ) : (
            <>
              <Space style={{ display: 'flex' }} size={16}>
                <Form.Item name="smtp_host" label="SMTP 服务器" rules={[{ required: true, message: '请输入 SMTP 服务器' }]} style={{ flex: 2 }}>
                  <Input placeholder="如：smtp.gmail.com" />
                </Form.Item>
                <Form.Item name="smtp_port" label="端口" style={{ flex: 1 }}>
                  <InputNumber min={1} max={65535} style={{ width: '100%' }} placeholder="587" />
                </Form.Item>
              </Space>
              <Form.Item name="smtp_user" label="SMTP 用户名" rules={[{ required: true, message: '请输入用户名' }]}>
                <Input placeholder="登录邮箱" autoComplete="username" />
              </Form.Item>
              <Form.Item name="smtp_pass" label={editing ? 'SMTP 密码（留空表示不改）' : 'SMTP 密码'} rules={editing ? [] : [{ required: true, message: '请输入密码' }]}>
                <Input.Password placeholder="密码或应用专用密码" autoComplete="new-password" />
              </Form.Item>
              <Form.Item name="from_addr" label="发件人地址（可选）" tooltip="为空则使用 SMTP 用户名">
                <Input placeholder="如：alerts@example.com" />
              </Form.Item>
              <Form.Item
                name="to_addrs"
                label="收件人"
                rules={[{ required: true, message: '请至少填写一个收件人' }]}
                tooltip="每行一个邮箱地址"
              >
                <Input.TextArea rows={3} placeholder={'ops@example.com\nadmin@example.com'} />
              </Form.Item>
            </>
          )}
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
      <TestResultModal result={testResult} open={testResultOpen} onClose={() => setTestResultOpen(false)} />
    </Card>
    </div>
  );
}
