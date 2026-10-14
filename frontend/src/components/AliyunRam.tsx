import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import { KeyOutlined, PlusOutlined, TeamOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { TenantOption } from '../api/tenants';
import {
  createRamAccessKey,
  createRamUser,
  deleteRamAccessKey,
  deleteRamUser,
  listRamAccessKeys,
  listRamUsers,
  type RamAccessKey,
  type RamUser,
} from '../api/aliyun';

const { Text } = Typography;

interface Props {
  tenantId: number | undefined;
  tenants: TenantOption[];
  onTenantChange: (id: number) => void;
}

/** 阿里云 RAM 用户管理：子用户 CRUD + AccessKey 管理（密钥明文仅创建时返回一次） */
export default function AliyunRam({ tenantId, tenants, onTenantChange }: Props) {
  const [loading, setLoading] = useState(false);
  const [users, setUsers] = useState<RamUser[]>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);
  const [form] = Form.useForm();

  const [keyUser, setKeyUser] = useState<RamUser | null>(null);
  const [keys, setKeys] = useState<RamAccessKey[]>([]);
  const [keysLoading, setKeysLoading] = useState(false);
  const [secretOnce, setSecretOnce] = useState<{ id: string; secret: string } | null>(null);

  const fetchUsers = useCallback(async () => {
    if (tenantId === undefined) return;
    setLoading(true);
    try {
      setUsers(await listRamUsers(tenantId));
    } catch {
      setUsers([]);
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const doCreate = async () => {
    if (tenantId === undefined) return;
    const v = await form.validateFields();
    setCreateLoading(true);
    try {
      const r = await createRamUser(tenantId, v);
      message.success(`RAM 用户 ${r.user_name} 已创建`);
      setCreateOpen(false);
      form.resetFields();
      fetchUsers();
    } finally {
      setCreateLoading(false);
    }
  };

  const doDelete = async (u: RamUser) => {
    if (tenantId === undefined) return;
    try {
      await deleteRamUser(tenantId, u.user_name);
      message.success(`RAM 用户 ${u.user_name} 已删除（含其 AccessKey）`);
      fetchUsers();
    } catch { /* 拦截器已提示 */ }
  };

  const openKeys = async (u: RamUser) => {
    setKeyUser(u);
    setSecretOnce(null);
    if (tenantId === undefined) return;
    setKeysLoading(true);
    try {
      setKeys(await listRamAccessKeys(tenantId, u.user_name));
    } catch {
      setKeys([]);
    } finally {
      setKeysLoading(false);
    }
  };

  const doCreateKey = async () => {
    if (tenantId === undefined || !keyUser) return;
    try {
      const r = await createRamAccessKey(tenantId, keyUser.user_name);
      setSecretOnce({ id: r.access_key_id, secret: r.access_key_secret });
      setKeys(await listRamAccessKeys(tenantId, keyUser.user_name));
      message.success('AccessKey 已创建，请立即复制保存');
    } catch { /* 拦截器已提示 */ }
  };

  const doDeleteKey = async (k: RamAccessKey) => {
    if (tenantId === undefined || !keyUser) return;
    try {
      await deleteRamAccessKey(tenantId, keyUser.user_name, k.access_key_id);
      message.success('AccessKey 已删除');
      setKeys(await listRamAccessKeys(tenantId, keyUser.user_name));
    } catch { /* 拦截器已提示 */ }
  };

  const columns: ColumnsType<RamUser> = [
    { title: '用户名', dataIndex: 'user_name', key: 'user_name', render: (v: string) => <Text strong>{v}</Text> },
    { title: '显示名', dataIndex: 'display_name', key: 'display_name' },
    { title: '邮箱', dataIndex: 'email', key: 'email' },
    { title: '手机', dataIndex: 'mobile', key: 'mobile' },
    {
      title: '创建时间',
      dataIndex: 'create_date',
      key: 'create_date',
      render: (v: string) => (v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '—'),
    },
    {
      title: '操作',
      key: 'action',
      render: (_, r) => (
        <Space>
          <Button size="small" icon={<KeyOutlined />} onClick={() => openKeys(r)}>
            AccessKey
          </Button>
          <Popconfirm
            title={`删除 RAM 用户 ${r.user_name}？其 AccessKey 会一并删除`}
            okText="删除"
            okType="danger"
            cancelText="取消"
            onConfirm={() => doDelete(r)}
          >
            <Button size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title={
        <Space>
          <TeamOutlined />
          RAM 用户管理
          <Select
            style={{ width: 260 }}
            placeholder="选择租户"
            value={tenantId}
            onChange={onTenantChange}
            options={tenants.map((t) => ({ label: `${t.name}（${t.region}）`, value: t.id }))}
          />
          <Tag color="orange">阿里云</Tag>
        </Space>
      }
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)} disabled={tenantId === undefined}>
          新建 RAM 用户
        </Button>
      }
    >
      <Table<RamUser> rowKey="user_name" columns={columns} dataSource={users} loading={loading} pagination={false} />

      <Modal title="新建 RAM 用户" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={doCreate} confirmLoading={createLoading} destroyOnClose>
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item name="user_name" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input placeholder="如 deploy-bot" />
          </Form.Item>
          <Form.Item name="display_name" label="显示名">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item name="email" label="邮箱">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item name="mobile_phone" label="手机号">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item name="comments" label="备注">
            <Input.TextArea rows={2} placeholder="可选" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={keyUser ? `${keyUser.user_name} 的 AccessKey` : 'AccessKey'}
        open={keyUser !== null}
        onCancel={() => setKeyUser(null)}
        footer={null}
        width={640}
        destroyOnClose
      >
        {secretOnce && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="请立即复制保存，关闭后无法再次查看 Secret"
            description={
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="AccessKeyId">
                  <Text copyable code>{secretOnce.id}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="AccessKeySecret">
                  <Text copyable code>{secretOnce.secret}</Text>
                </Descriptions.Item>
              </Descriptions>
            }
          />
        )}
        <Space style={{ marginBottom: 12 }}>
          <Button type="primary" size="small" icon={<PlusOutlined />} onClick={doCreateKey}>
            创建 AccessKey
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>每个用户最多 2 个 AccessKey</Text>
        </Space>
        <Table<RamAccessKey>
          rowKey="access_key_id"
          size="small"
          loading={keysLoading}
          pagination={false}
          dataSource={keys}
          columns={[
            { title: 'AccessKeyId', dataIndex: 'access_key_id', key: 'access_key_id', render: (v: string) => <Text code copyable>{v}</Text> },
            {
              title: '状态',
              dataIndex: 'status',
              key: 'status',
              render: (v: string) => <Tag color={v === 'Active' ? 'green' : 'default'}>{v}</Tag>,
            },
            { title: '创建时间', dataIndex: 'create_date', key: 'create_date' },
            {
              title: '操作',
              key: 'action',
              render: (_, k) => (
                <Popconfirm title="删除这个 AccessKey？" okText="删除" okType="danger" cancelText="取消" onConfirm={() => doDeleteKey(k)}>
                  <Button size="small" danger>删除</Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </Modal>
    </Card>
  );
}
