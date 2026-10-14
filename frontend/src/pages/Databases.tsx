import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Form,
  Input,
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
import {
  DatabaseOutlined,
  DownloadOutlined,
  KeyOutlined,
  PlusOutlined,
  PoweroffOutlined,
  RedoOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { listTenants, type TenantOption } from '../api/tenants';
import { getCompartments, type Compartment } from '../api/meta';
import {
  changeDbPassword,
  createDatabase,
  deleteDatabase,
  downloadWallet,
  getDatabase,
  listDatabases,
  restartDatabase,
  startDatabase,
  stopDatabase,
  type AutonomousDb,
  type AutonomousDbDetail,
} from '../api/databases';

const { Paragraph, Text } = Typography;

const WORKLOAD_OPTIONS = [
  { value: 'OLTP', label: '事务处理（OLTP）' },
  { value: 'DW', label: '数据仓库（DW）' },
  { value: 'AJD', label: 'JSON 数据库（AJD）' },
  { value: 'APEX', label: 'APEX 低代码（APEX）' },
];

function stateColor(s: string): string {
  switch (s) {
    case 'AVAILABLE': return 'green';
    case 'STOPPED': return 'default';
    case 'TERMINATED': case 'TERMINATING': return 'red';
    default: return 'blue';
  }
}

const fmtGB = (tbs: number | null | undefined) =>
  tbs == null ? '-' : `${(tbs * 1024).toFixed(1)} GB`;

/** 数据库管理页：Oracle Autonomous Database（全部实时 OCI 接口） */
export default function Databases() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number>();
  const [compartments, setCompartments] = useState<Compartment[]>([]);
  const [compartmentId, setCompartmentId] = useState('');
  const [dbs, setDbs] = useState<AutonomousDb[]>([]);
  const [loading, setLoading] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm();
  const [creating, setCreating] = useState(false);

  const [detailDb, setDetailDb] = useState<AutonomousDbDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const [pwdDb, setPwdDb] = useState<AutonomousDb | null>(null);
  const [pwdForm] = Form.useForm();

  const [walletDb, setWalletDb] = useState<AutonomousDb | null>(null);
  const [walletForm] = Form.useForm();
  const [walletLoading, setWalletLoading] = useState(false);

  const fetchDbs = useCallback(async (tid: number, cid: string) => {
    setLoading(true);
    try {
      setDbs(await listDatabases(tid, cid));
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '查询失败');
      setDbs([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // 租户列表
  useEffect(() => {
    listTenants().then((ts) => {
      setTenants(ts);
      if (ts.length > 0) setTenantId(ts[0].id);
    }).catch(() => {});
  }, []);

  // 切换租户 → 拉 compartment
  useEffect(() => {
    if (!tenantId) return;
    getCompartments(tenantId).then((cs) => {
      setCompartments(cs);
      const root = cs[0]?.id || '';
      setCompartmentId(root);
      if (root) fetchDbs(tenantId, root);
    }).catch(() => { setCompartments([]); });
  }, [tenantId, fetchDbs]);

  const refresh = () => {
    if (tenantId && compartmentId) fetchDbs(tenantId, compartmentId);
  };

  const doOp = async (fn: () => Promise<unknown>, okMsg: string) => {
    try {
      await fn();
      message.success(okMsg);
      refresh();
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '操作失败');
    }
  };

  const openDetail = async (db: AutonomousDb) => {
    if (!tenantId) return;
    try {
      const d = await getDatabase(tenantId, db.id);
      setDetailDb(d);
      setDetailOpen(true);
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '查询详情失败');
    }
  };

  const submitCreate = async () => {
    if (!tenantId) return;
    const v = await createForm.validateFields();
    setCreating(true);
    try {
      await createDatabase({
        tenant_id: tenantId,
        compartment_id: compartmentId,
        db_name: v.db_name.trim().toUpperCase(),
        display_name: v.display_name?.trim() || undefined,
        db_workload: v.db_workload,
        admin_password: v.admin_password,
        is_free_tier: v.is_free_tier ?? true,
        db_version: v.db_version,
      });
      message.success('已提交创建，数据库正在配置中（PROVISIONING），稍后刷新查看');
      setCreateOpen(false);
      createForm.resetFields();
      refresh();
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '创建失败');
    } finally {
      setCreating(false);
    }
  };

  const submitPwd = async () => {
    if (!tenantId || !pwdDb) return;
    const v = await pwdForm.validateFields();
    await doOp(() => changeDbPassword(tenantId, pwdDb.id, v.new_password), 'ADMIN 密码已修改');
    setPwdDb(null);
    pwdForm.resetFields();
  };

  const submitWallet = async () => {
    if (!tenantId || !walletDb) return;
    const v = await walletForm.validateFields();
    setWalletLoading(true);
    try {
      const { url, filename } = await downloadWallet(tenantId, walletDb.id, v.wallet_password);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
      message.success('Wallet 已开始下载');
      setWalletDb(null);
      walletForm.resetFields();
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '下载失败');
    } finally {
      setWalletLoading(false);
    }
  };

  const columns: ColumnsType<AutonomousDb> = [
    { title: '名称', dataIndex: 'display_name', key: 'display_name', render: (v, r) => <><Text strong>{v}</Text><br /><Text type="secondary" style={{ fontSize: 12 }}>{r.db_name}</Text></> },
    {
      title: '类型', dataIndex: 'db_workload', key: 'workload',
      render: (v: string, r) => <Tag>{r.db_workload_cn || v}</Tag>,
    },
    { title: '版本', dataIndex: 'db_version', key: 'db_version' },
    {
      title: '状态', dataIndex: 'lifecycle_state', key: 'state',
      render: (v: string) => <Tag color={stateColor(v)}>{v}</Tag>,
    },
    {
      title: '免费版', dataIndex: 'is_free_tier', key: 'free',
      render: (v: boolean) => v ? <Tag color="green">Always Free</Tag> : <Tag>付费</Tag>,
    },
    {
      title: '存储', key: 'storage',
      render: (_, r) => <>{fmtGB(r.actual_used_data_storage_size_in_tbs)}<Text type="secondary"> / {fmtGB(r.allocated_storage_size_in_tbs)}</Text></>,
    },
    {
      title: '算力', key: 'compute',
      render: (_, r) => r.compute_count != null ? `${r.compute_count} ${r.compute_model || ''}`.trim() : '-',
    },
    { title: '创建时间', dataIndex: 'time_created', key: 'time_created', render: (v: string | null) => v ? new Date(v).toLocaleString() : '-' },
    {
      title: '操作', key: 'op', width: 340,
      render: (_, r) => (
        <Space size="small" wrap>
          <Button size="small" onClick={() => openDetail(r)}>详情</Button>
          {r.lifecycle_state === 'STOPPED' && (
            <Popconfirm title="确定启动该数据库吗？" onConfirm={() => tenantId && doOp(() => startDatabase(tenantId, r.id), '已提交启动')}>
              <Button size="small" type="primary">启动</Button>
            </Popconfirm>
          )}
          {r.lifecycle_state === 'AVAILABLE' && (
            <>
              <Popconfirm title="确定停止该数据库吗？停止后连接将中断。" onConfirm={() => tenantId && doOp(() => stopDatabase(tenantId, r.id), '已提交停止')}>
                <Button size="small" icon={<PoweroffOutlined />} danger>停止</Button>
              </Popconfirm>
              <Popconfirm title="确定重启该数据库吗？" onConfirm={() => tenantId && doOp(() => restartDatabase(tenantId, r.id), '已提交重启')}>
                <Button size="small" icon={<RedoOutlined />}>重启</Button>
              </Popconfirm>
            </>
          )}
          <Button size="small" icon={<KeyOutlined />} onClick={() => setPwdDb(r)}>改密</Button>
          <Button size="small" icon={<DownloadOutlined />} onClick={() => setWalletDb(r)}>Wallet</Button>
          <Popconfirm
            title="删除数据库"
            description="删除后所有数据不可恢复，确定删除吗？"
            okText="删除" cancelText="取消" okButtonProps={{ danger: true }}
            onConfirm={() => tenantId && doOp(() => deleteDatabase(tenantId, r.id), '已提交删除')}
          >
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            style={{ width: 240 }} placeholder="选择租户" value={tenantId}
            onChange={setTenantId} options={tenants.map((t) => ({ value: t.id, label: t.name }))}
          />
          <Select
            style={{ width: 280 }} placeholder="选择 Compartment" value={compartmentId || undefined}
            onChange={(v) => { setCompartmentId(v); if (tenantId) fetchDbs(tenantId, v); }}
            options={compartments.map((c) => ({ value: c.id, label: c.name }))}
            showSearch optionFilterProp="label"
          />
          <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)} disabled={!tenantId || !compartmentId}>
            新建数据库
          </Button>
        </Space>
        <div style={{ marginTop: 8 }}>
          <Alert
            type="info" showIcon
            message="Always Free 免费账号可创建最多 2 个自治数据库（每库 20GB）。ADMIN 与 Wallet 密码仅在请求中透传，面板不做存储。"
          />
        </div>
      </Card>

      <Card>
        <Table<AutonomousDb>
          rowKey="id" columns={columns} dataSource={dbs} loading={loading}
          pagination={false} scroll={{ x: 1200 }}
          locale={{ emptyText: '该 Compartment 下暂无自治数据库' }}
        />
      </Card>

      {/* 新建 */}
      <Modal title="新建自治数据库" open={createOpen} onCancel={() => setCreateOpen(false)}
        onOk={submitCreate} confirmLoading={creating} okText="创建" width={560}>
        <Form form={createForm} layout="vertical" initialValues={{ db_workload: 'OLTP', is_free_tier: true, db_version: '26ai' }}>
          <Form.Item name="db_name" label="库名" rules={[{ required: true, message: '请输入库名' }, { pattern: /^[A-Za-z][A-Za-z0-9]{0,13}$/, message: '1-14 字符，字母开头，仅字母数字' }]}
            extra="创建后不可修改">
            <Input placeholder="如 MYDB" maxLength={14} style={{ textTransform: 'uppercase' }} />
          </Form.Item>
          <Form.Item name="display_name" label="显示名"><Input placeholder="默认与库名相同" /></Form.Item>
          <Form.Item name="db_workload" label="工作负载类型">
            <Select options={WORKLOAD_OPTIONS} />
          </Form.Item>
          <Form.Item name="db_version" label="数据库版本">
            <Select options={[{ value: '26ai', label: '26ai' }, { value: '23ai', label: '23ai' }, { value: '19c', label: '19c' }]} />
          </Form.Item>
          <Form.Item name="admin_password" label="ADMIN 密码"
            rules={[{ required: true, message: '请输入 ADMIN 密码' }, { min: 12, message: '至少 12 位' }]}
            extra="至少 12 位，须含大小写字母和数字。密码仅透传给 OCI，面板不存储。">
            <Input.Password placeholder="请输入 ADMIN 密码" />
          </Form.Item>
          <Form.Item name="is_free_tier" label="Always Free 免费版" valuePropName="checked">
            <Switch checkedChildren="免费" unCheckedChildren="付费" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 详情 */}
      <Drawer title="数据库详情" open={detailOpen} onClose={() => setDetailOpen(false)} width={640}>
        {detailDb && (
          <>
            <Descriptions column={1} bordered size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="显示名">{detailDb.display_name}</Descriptions.Item>
              <Descriptions.Item label="库名">{detailDb.db_name}</Descriptions.Item>
              <Descriptions.Item label="类型">{detailDb.db_workload_cn}（{detailDb.db_workload}）</Descriptions.Item>
              <Descriptions.Item label="状态"><Tag color={stateColor(detailDb.lifecycle_state)}>{detailDb.lifecycle_state}</Tag></Descriptions.Item>
              <Descriptions.Item label="存储">已用 {fmtGB(detailDb.actual_used_data_storage_size_in_tbs)} / 分配 {fmtGB(detailDb.allocated_storage_size_in_tbs)}</Descriptions.Item>
              <Descriptions.Item label="算力">{detailDb.compute_count} {detailDb.compute_model || ''}</Descriptions.Item>
              {detailDb.service_console_url && (
                <Descriptions.Item label="控制台">
                  <a href={detailDb.service_console_url} target="_blank" rel="noreferrer">在 OCI 控制台打开</a>
                </Descriptions.Item>
              )}
            </Descriptions>
            <Text strong>连接串（TLS 连接用）</Text>
            {detailDb.connection_profiles && Object.keys(detailDb.connection_profiles).length > 0 ? (
              Object.entries(detailDb.connection_profiles).map(([k, v]) => (
                <div key={k} style={{ marginTop: 8 }}>
                  <Text type="secondary">{k}</Text>
                  <Paragraph copyable={{ text: v }} ellipsis={{ rows: 2, expandable: true }}>{v}</Paragraph>
                </div>
              ))
            ) : (
              <Paragraph type="secondary">暂无连接串（数据库可能尚未 AVAILABLE）</Paragraph>
            )}
          </>
        )}
      </Drawer>

      {/* 改密 */}
      <Modal title={`修改 ADMIN 密码 - ${pwdDb?.display_name}`} open={!!pwdDb}
        onCancel={() => setPwdDb(null)} onOk={submitPwd} okText="修改" okButtonProps={{ danger: true }}>
        <Form form={pwdForm} layout="vertical">
          <Form.Item name="new_password" label="新密码"
            rules={[{ required: true, message: '请输入新密码' }, { min: 12, message: '至少 12 位' }]}
            extra="至少 12 位，须含大小写字母和数字。密码仅透传，面板不存储。">
            <Input.Password placeholder="请输入新 ADMIN 密码" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Wallet */}
      <Modal title={<Space><DatabaseOutlined />下载连接 Wallet - {walletDb?.display_name}</Space>}
        open={!!walletDb} onCancel={() => setWalletDb(null)} onOk={submitWallet}
        confirmLoading={walletLoading} okText="下载">
        <Form form={walletForm} layout="vertical">
          <Form.Item name="wallet_password" label="Wallet 压缩包密码"
            rules={[{ required: true, message: '请输入密码' }, { min: 8, message: '至少 8 位' }]}
            extra="下载的是 zip 压缩包，用于 SQL Developer / DBeaver 等客户端连接。密码仅透传，面板不存储。">
            <Input.Password placeholder="至少 8 位" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
