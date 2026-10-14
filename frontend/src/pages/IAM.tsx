import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Drawer,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import { KeyOutlined, PlusOutlined, SafetyOutlined, TeamOutlined, UserOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { listTenants, type TenantOption } from '../api/tenants';
import AliyunRam from '../components/AliyunRam';
import {
  addGroupMember,
  createAuthToken,
  createIamGroup,
  createIamUser,
  createSecretKey,
  createSmtpCredential,
  deleteApiKey,
  deleteAuthToken,
  deleteIamGroup,
  deleteIamUser,
  deleteMfaDevice,
  deleteSecretKey,
  deleteSmtpCredential,
  listApiKeys,
  listAuthTokens,
  listGroupMembers,
  listIamGroups,
  listIamUsers,
  listMfaDevices,
  listSecretKeys,
  listSmtpCredentials,
  removeGroupMember,
  updateIamUser,
  uploadApiKey,
  type ApiKey,
  type AuthToken,
  type GroupMember,
  type IamGroup,
  type IamUser,
  type MfaDevice,
  type SecretKey,
  type SmtpCredential,
} from '../api/iam';

const { TextArea } = Input;
const { Paragraph } = Typography;

/** IAM 用户管理页：OCI 用户 / API 密钥 / 用户组 / 令牌凭证 / MFA（全部实时接口） */
export default function IAM() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number>();
  const [loading, setLoading] = useState(false);
  const [users, setUsers] = useState<IamUser[]>([]);
  const [groups, setGroups] = useState<IamGroup[]>([]);

  // 新建/编辑用户
  const [userOpen, setUserOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<IamUser | null>(null);
  const [userForm] = Form.useForm();
  // API 密钥
  const [keyUser, setKeyUser] = useState<IamUser | null>(null);
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [keyForm] = Form.useForm();
  // 令牌凭证
  const [credUser, setCredUser] = useState<IamUser | null>(null);
  const [authTokens, setAuthTokens] = useState<AuthToken[]>([]);
  const [secretKeys, setSecretKeys] = useState<SecretKey[]>([]);
  const [smtpCreds, setSmtpCreds] = useState<SmtpCredential[]>([]);
  const [mfaDevices, setMfaDevices] = useState<MfaDevice[]>([]);
  const [credForm] = Form.useForm();
  // 一次性密钥展示
  const [secretOnce, setSecretOnce] = useState<{ title: string; label: string; value: string } | null>(null);
  // 用户组
  const [groupOpen, setGroupOpen] = useState(false);
  const [groupForm] = Form.useForm();
  const [memberGroup, setMemberGroup] = useState<IamGroup | null>(null);
  const [members, setMembers] = useState<GroupMember[]>([]);
  const [addMemberUserId, setAddMemberUserId] = useState<string>();

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const ts = await listTenants();
      setTenants(ts);
      if (ts.length > 0) setTenantId((prev) => prev ?? ts[0].id);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchIam = useCallback(async () => {
    if (tenantId === undefined) return;
    setLoading(true);
    try {
      const [us, gs] = await Promise.all([listIamUsers(tenantId), listIamGroups(tenantId)]);
      setUsers(us);
      setGroups(gs);
    } catch {
      setUsers([]);
      setGroups([]);
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);
  useEffect(() => {
    fetchIam();
  }, [fetchIam]);

  const doAction = async (fn: () => Promise<unknown>, okMsg: string) => {
    try {
      await fn();
      message.success(okMsg);
      fetchIam();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const userName = (id: string) => users.find((u) => u.id === id)?.name ?? id.slice(-12);

  /* ---------- 用户 ---------- */
  const openCreateUser = () => {
    setEditingUser(null);
    userForm.resetFields();
    setUserOpen(true);
  };
  const openEditUser = (u: IamUser) => {
    setEditingUser(u);
    userForm.setFieldsValue({ description: u.description, email: u.email });
    setUserOpen(true);
  };
  const submitUser = async () => {
    if (tenantId === undefined) return;
    const v = await userForm.validateFields();
    if (editingUser) {
      await doAction(() => updateIamUser(tenantId, editingUser.id, v), '用户已更新');
    } else {
      await doAction(() => createIamUser(tenantId, v), '用户已创建');
    }
    setUserOpen(false);
  };
  const confirmDeleteUser = (u: IamUser) => {
    Modal.confirm({
      title: `删除用户 ${u.name}？`,
      content: '删除后不可恢复；若面板的租户配置正在使用该用户的 API 密钥，该租户将失效。请先确认。',
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => {
        if (tenantId === undefined) return;
        return doAction(() => deleteIamUser(tenantId, u.id), '用户已删除');
      },
    });
  };

  /* ---------- API 密钥 ---------- */
  const openApiKeys = async (u: IamUser) => {
    setKeyUser(u);
    keyForm.resetFields();
    if (tenantId !== undefined) setApiKeys(await listApiKeys(tenantId, u.id).catch(() => []));
  };
  const submitApiKey = async () => {
    if (tenantId === undefined || !keyUser) return;
    const v = await keyForm.validateFields();
    await doAction(() => uploadApiKey(tenantId, keyUser.id, v.public_key_pem), 'API 公钥已上传');
    setApiKeys(await listApiKeys(tenantId, keyUser.id).catch(() => []));
    keyForm.resetFields();
  };

  /* ---------- 令牌凭证 ---------- */
  const openCreds = async (u: IamUser) => {
    setCredUser(u);
    credForm.resetFields();
    if (tenantId === undefined) return;
    const [at, sk, sc, mfa] = await Promise.all([
      listAuthTokens(tenantId, u.id).catch(() => [] as AuthToken[]),
      listSecretKeys(tenantId, u.id).catch(() => [] as SecretKey[]),
      listSmtpCredentials(tenantId, u.id).catch(() => [] as SmtpCredential[]),
      listMfaDevices(tenantId, u.id).catch(() => [] as MfaDevice[]),
    ]);
    setAuthTokens(at);
    setSecretKeys(sk);
    setSmtpCreds(sc);
    setMfaDevices(mfa);
  };
  const refreshCreds = async () => {
    if (credUser && tenantId !== undefined) await openCreds(credUser);
  };
  /** 创建后只显示一次的密钥：弹窗展示 + 复制 */
  const showOnce = (title: string, label: string, value: string) => {
    setSecretOnce({ title, label, value });
    refreshCreds();
  };

  /* ---------- 用户组 ---------- */
  const openMembers = async (g: IamGroup) => {
    setMemberGroup(g);
    setAddMemberUserId(undefined);
    if (tenantId !== undefined) setMembers(await listGroupMembers(tenantId, g.id).catch(() => []));
  };
  const submitAddMember = async () => {
    if (tenantId === undefined || !memberGroup || !addMemberUserId) return;
    await doAction(() => addGroupMember(tenantId, memberGroup.id, addMemberUserId), '已加入用户组');
    setMembers(await listGroupMembers(tenantId, memberGroup.id).catch(() => []));
    setAddMemberUserId(undefined);
  };

  const userColumns: ColumnsType<IamUser> = [
    { title: '用户名', dataIndex: 'name', key: 'name', width: 200 },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    { title: '邮箱', dataIndex: 'email', key: 'email', width: 200, ellipsis: true },
    {
      title: 'MFA',
      key: 'mfa',
      width: 90,
      render: (_, r) =>
        r.is_mfa_activated ? <Tag color="success">已启用</Tag> : <Tag>未启用</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'lifecycle_state',
      key: 'lifecycle_state',
      width: 100,
      render: (s: string) => <Tag color={s === 'ACTIVE' ? 'success' : 'default'}>{s}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 300,
      render: (_, r) => (
        <Space size="small">
          <Button size="small" icon={<KeyOutlined />} onClick={() => openApiKeys(r)}>
            API 密钥
          </Button>
          <Button size="small" icon={<SafetyOutlined />} onClick={() => openCreds(r)}>
            令牌凭证
          </Button>
          <Button size="small" onClick={() => openEditUser(r)}>
            编辑
          </Button>
          <Button size="small" danger onClick={() => confirmDeleteUser(r)}>
            删除
          </Button>
        </Space>
      ),
    },
  ];

  const groupColumns: ColumnsType<IamGroup> = [
    { title: '组名', dataIndex: 'name', key: 'name', width: 220 },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'lifecycle_state',
      key: 'lifecycle_state',
      width: 100,
      render: (s: string) => <Tag color={s === 'ACTIVE' ? 'success' : 'default'}>{s}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 220,
      render: (_, r) => (
        <Space size="small">
          <Button size="small" icon={<TeamOutlined />} onClick={() => openMembers(r)}>
            成员管理
          </Button>
          <Button
            size="small"
            danger
            onClick={() =>
              Modal.confirm({
                title: `删除用户组 ${r.name}？`,
                okText: '确认删除',
                okType: 'danger',
                cancelText: '取消',
                onOk: () => {
                  if (tenantId === undefined) return;
                  return doAction(() => deleteIamGroup(tenantId, r.id), '用户组已删除');
                },
              })
            }
          >
            删除
          </Button>
        </Space>
      ),
    },
  ];

  const credDeletable = (state: string) => state === 'ACTIVE';

  // 阿里云租户走 RAM 管理界面（OCI IAM 接口不适用）
  const currentTenant = tenants.find((t) => t.id === tenantId);
  if (currentTenant?.provider === 'aliyun') {
    return <AliyunRam tenantId={tenantId} tenants={tenants} onTenantChange={setTenantId} />;
  }

  return (
    <Card
      title={
        <Space>
          <UserOutlined />
          IAM 用户管理
          <Select
            style={{ width: 260 }}
            placeholder="选择租户"
            value={tenantId}
            onChange={setTenantId}
            options={tenants.map((t) => ({ label: `${t.name}（${t.region}）`, value: t.id }))}
          />
        </Space>
      }
    >
      <Tabs
        defaultActiveKey="users"
        items={[
          {
            key: 'users',
            label: '用户',
            children: (
              <>
                <Button type="primary" icon={<PlusOutlined />} onClick={openCreateUser} style={{ marginBottom: 16 }}>
                  新建用户
                </Button>
                <Table<IamUser> rowKey="id" columns={userColumns} dataSource={users} loading={loading} scroll={{ x: 1100 }} />
              </>
            ),
          },
          {
            key: 'groups',
            label: '用户组',
            children: (
              <>
                <Button
                  type="primary"
                  icon={<PlusOutlined />}
                  style={{ marginBottom: 16 }}
                  onClick={() => {
                    groupForm.resetFields();
                    setGroupOpen(true);
                  }}
                >
                  新建用户组
                </Button>
                <Table<IamGroup> rowKey="id" columns={groupColumns} dataSource={groups} loading={loading} />
              </>
            ),
          },
        ]}
      />

      {/* 新建/编辑用户 */}
      <Modal
        title={editingUser ? `编辑用户（${editingUser.name}）` : '新建用户'}
        open={userOpen}
        onCancel={() => setUserOpen(false)}
        onOk={submitUser}
        destroyOnClose
      >
        <Form form={userForm} layout="vertical">
          {!editingUser && (
            <Form.Item name="name" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
              <Input placeholder="如：ops-admin（创建后不可改）" />
            </Form.Item>
          )}
          <Form.Item name="description" label="描述">
            <Input placeholder="用户用途说明" />
          </Form.Item>
          <Form.Item name="email" label="邮箱">
            <Input placeholder="可选" />
          </Form.Item>
        </Form>
      </Modal>

      {/* API 密钥 */}
      <Modal
        title={keyUser ? `${keyUser.name} 的 API 密钥` : 'API 密钥'}
        open={!!keyUser}
        onCancel={() => setKeyUser(null)}
        footer={null}
        width={720}
        destroyOnClose
      >
        <Table<ApiKey>
          rowKey="fingerprint"
          size="small"
          pagination={false}
          dataSource={apiKeys}
          columns={[
            { title: '指纹', dataIndex: 'fingerprint', key: 'fingerprint', ellipsis: true },
            { title: '创建时间', dataIndex: 'time_created', key: 'time_created', width: 170, render: (v: string | null) => (v ? v.slice(0, 19).replace('T', ' ') : '-') },
            {
              title: '操作',
              key: 'action',
              width: 100,
              render: (_, r) => (
                <Button
                  size="small"
                  danger
                  onClick={() =>
                    Modal.confirm({
                      title: '删除该 API 密钥？',
                      content: '使用该密钥的程序/租户配置将立即失效。',
                      okText: '确认删除',
                      okType: 'danger',
                      cancelText: '取消',
                      onOk: async () => {
                        if (tenantId === undefined || !keyUser) return;
                        await doAction(() => deleteApiKey(tenantId, keyUser.id, r.fingerprint), 'API 密钥已删除');
                        setApiKeys(await listApiKeys(tenantId, keyUser.id).catch(() => []));
                      },
                    })
                  }
                >
                  删除
                </Button>
              ),
            },
          ]}
        />
        <Form form={keyForm} layout="vertical" style={{ marginTop: 16 }} onFinish={submitApiKey}>
          <Form.Item
            name="public_key_pem"
            label="上传新公钥"
            rules={[{ required: true, message: '请粘贴 PEM 格式公钥' }]}
          >
            <TextArea rows={4} placeholder="-----BEGIN PUBLIC KEY-----&#10;...&#10;-----END PUBLIC KEY-----" />
          </Form.Item>
          <Button type="primary" htmlType="submit">
            上传公钥
          </Button>
        </Form>
      </Modal>

      {/* 令牌凭证 */}
      <Modal
        title={credUser ? `${credUser.name} 的令牌与凭证` : '令牌与凭证'}
        open={!!credUser}
        onCancel={() => setCredUser(null)}
        footer={null}
        width={760}
        destroyOnClose
      >
        <Tabs
          defaultActiveKey="auth"
          items={[
            {
              key: 'auth',
              label: 'Auth Token',
              children: (
                <>
                  <Form form={credForm} layout="inline" style={{ marginBottom: 12 }} onFinish={async () => {
                    if (tenantId === undefined || !credUser) return;
                    const v = await credForm.validateFields();
                    const r = await createAuthToken(tenantId, credUser.id, v.description);
                    message.success('Auth Token 已创建');
                    showOnce('Auth Token 创建成功', 'Token（只显示一次，请立即复制保存）', r.token);
                    credForm.resetFields();
                  }}>
                    <Form.Item name="description" label="描述">
                      <Input placeholder="用途说明（可选）" />
                    </Form.Item>
                    <Form.Item>
                      <Button type="primary" htmlType="submit">
                        创建
                      </Button>
                    </Form.Item>
                  </Form>
                  <Table<AuthToken>
                    rowKey="id"
                    size="small"
                    pagination={false}
                    dataSource={authTokens}
                    columns={[
                      { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
                      { title: '创建时间', dataIndex: 'time_created', key: 'time_created', width: 160, render: (v: string | null) => (v ? v.slice(0, 19).replace('T', ' ') : '-') },
                      {
                        title: '操作', key: 'action', width: 90,
                        render: (_, r) => credDeletable(r.lifecycle_state) && (
                          <Button size="small" danger onClick={async () => {
                            if (tenantId === undefined || !credUser) return;
                            await doAction(() => deleteAuthToken(tenantId, credUser.id, r.id), '已删除');
                            refreshCreds();
                          }}>
                            删除
                          </Button>
                        ),
                      },
                    ]}
                  />
                </>
              ),
            },
            {
              key: 'secret',
              label: 'Secret Key',
              children: (
                <>
                  <Form layout="inline" style={{ marginBottom: 12 }} onFinish={async (v: { display_name?: string }) => {
                    if (tenantId === undefined || !credUser) return;
                    const r = await createSecretKey(tenantId, credUser.id, v.display_name);
                    message.success('Secret Key 已创建');
                    showOnce('Secret Key 创建成功', 'Secret Key（只显示一次，请立即复制保存）', r.key);
                  }}>
                    <Form.Item name="display_name" label="名称">
                      <Input placeholder="可选" />
                    </Form.Item>
                    <Form.Item>
                      <Button type="primary" htmlType="submit">
                        创建
                      </Button>
                    </Form.Item>
                  </Form>
                  <Table<SecretKey>
                    rowKey="id"
                    size="small"
                    pagination={false}
                    dataSource={secretKeys}
                    columns={[
                      { title: '名称', dataIndex: 'display_name', key: 'display_name', ellipsis: true },
                      { title: '创建时间', dataIndex: 'time_created', key: 'time_created', width: 160, render: (v: string | null) => (v ? v.slice(0, 19).replace('T', ' ') : '-') },
                      {
                        title: '操作', key: 'action', width: 90,
                        render: (_, r) => credDeletable(r.lifecycle_state) && (
                          <Button size="small" danger onClick={async () => {
                            if (tenantId === undefined || !credUser) return;
                            await doAction(() => deleteSecretKey(tenantId, credUser.id, r.id), '已删除');
                            refreshCreds();
                          }}>
                            删除
                          </Button>
                        ),
                      },
                    ]}
                  />
                </>
              ),
            },
            {
              key: 'smtp',
              label: 'SMTP 凭证',
              children: (
                <>
                  <Form layout="inline" style={{ marginBottom: 12 }} onFinish={async (v: { description?: string }) => {
                    if (tenantId === undefined || !credUser) return;
                    const r = await createSmtpCredential(tenantId, credUser.id, v.description);
                    message.success('SMTP 凭证已创建');
                    showOnce('SMTP 凭证创建成功', `用户名 ${r.username} 的密码（只显示一次，请立即复制保存）`, r.password);
                  }}>
                    <Form.Item name="description" label="描述">
                      <Input placeholder="可选" />
                    </Form.Item>
                    <Form.Item>
                      <Button type="primary" htmlType="submit">
                        创建
                      </Button>
                    </Form.Item>
                  </Form>
                  <Table<SmtpCredential>
                    rowKey="id"
                    size="small"
                    pagination={false}
                    dataSource={smtpCreds}
                    columns={[
                      { title: '用户名', dataIndex: 'username', key: 'username', ellipsis: true },
                      { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
                      {
                        title: '操作', key: 'action', width: 90,
                        render: (_, r) => credDeletable(r.lifecycle_state) && (
                          <Button size="small" danger onClick={async () => {
                            if (tenantId === undefined || !credUser) return;
                            await doAction(() => deleteSmtpCredential(tenantId, credUser.id, r.id), '已删除');
                            refreshCreds();
                          }}>
                            删除
                          </Button>
                        ),
                      },
                    ]}
                  />
                </>
              ),
            },
            {
              key: 'mfa',
              label: 'MFA 设备',
              children: (
                <Table<MfaDevice>
                  rowKey="id"
                  size="small"
                  pagination={false}
                  dataSource={mfaDevices}
                  columns={[
                    { title: '设备 ID', dataIndex: 'id', key: 'id', ellipsis: true },
                    { title: '状态', dataIndex: 'lifecycle_state', key: 'lifecycle_state', width: 110, render: (s: string) => <Tag color={s === 'ACTIVE' ? 'success' : 'default'}>{s}</Tag> },
                    {
                      title: '操作', key: 'action', width: 90,
                      render: (_, r) => (
                        <Button size="small" danger onClick={async () => {
                          if (tenantId === undefined || !credUser) return;
                          await doAction(() => deleteMfaDevice(tenantId, credUser.id, r.id), 'MFA 设备已删除');
                          refreshCreds();
                        }}>
                          删除
                        </Button>
                      ),
                    },
                  ]}
                />
              ),
            },
          ]}
        />
      </Modal>

      {/* 一次性密钥展示 */}
      <Modal
        title={secretOnce?.title}
        open={!!secretOnce}
        onCancel={() => setSecretOnce(null)}
        footer={[
          <Button key="ok" type="primary" onClick={() => setSecretOnce(null)}>
            我已保存，关闭
          </Button>,
        ]}
        destroyOnClose
      >
        <Alert
          type="warning"
          showIcon
          message="只显示一次"
          description="关闭此弹窗后将无法再次查看，请立即复制保存到安全的地方。"
          style={{ marginBottom: 16 }}
        />
        <Paragraph copyable={{ text: secretOnce?.value }}>{secretOnce?.label}</Paragraph>
        <Paragraph copyable code style={{ wordBreak: 'break-all' }}>
          {secretOnce?.value}
        </Paragraph>
      </Modal>

      {/* 新建用户组 */}
      <Modal
        title="新建用户组"
        open={groupOpen}
        onCancel={() => setGroupOpen(false)}
        onOk={async () => {
          if (tenantId === undefined) return;
          const v = await groupForm.validateFields();
          await doAction(() => createIamGroup(tenantId, v), '用户组已创建');
          setGroupOpen(false);
        }}
        destroyOnClose
      >
        <Form form={groupForm} layout="vertical">
          <Form.Item name="name" label="组名" rules={[{ required: true, message: '请输入组名' }]}>
            <Input placeholder="如：admins（创建后不可改）" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input placeholder="用户组用途说明" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 成员管理 */}
      <Drawer
        title={memberGroup ? `${memberGroup.name} 的成员` : '成员管理'}
        open={!!memberGroup}
        onClose={() => setMemberGroup(null)}
        width={520}
        destroyOnClose
      >
        <Space.Compact style={{ width: '100%', marginBottom: 16 }}>
          <Select
            style={{ flex: 1 }}
            placeholder="选择用户加入"
            showSearch
            optionFilterProp="label"
            value={addMemberUserId}
            onChange={setAddMemberUserId}
            options={users.map((u) => ({ value: u.id, label: u.name }))}
          />
          <Button type="primary" onClick={submitAddMember} disabled={!addMemberUserId}>
            添加
          </Button>
        </Space.Compact>
        <Table<GroupMember>
          rowKey="membership_id"
          size="small"
          pagination={false}
          dataSource={members}
          columns={[
            { title: '用户', dataIndex: 'user_id', key: 'user_id', render: (id: string) => userName(id) },
            {
              title: '操作',
              key: 'action',
              width: 90,
              render: (_, r) => (
                <Button
                  size="small"
                  danger
                  onClick={async () => {
                    if (tenantId === undefined || !memberGroup) return;
                    await doAction(() => removeGroupMember(tenantId, memberGroup.id, r.membership_id), '已移除');
                    setMembers(await listGroupMembers(tenantId, memberGroup.id).catch(() => []));
                  }}
                >
                  移除
                </Button>
              ),
            },
          ]}
        />
      </Drawer>
    </Card>
  );
}
