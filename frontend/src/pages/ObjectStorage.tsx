import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Divider,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import {
  DeleteOutlined,
  DownloadOutlined,
  LinkOutlined,
  PlusOutlined,
  ReloadOutlined,
  SettingOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { UploadProps } from 'antd';
import { listTenants, type TenantOption } from '../api/tenants';
import {
  createBucket,
  createPar,
  deleteBucket,
  deleteObject,
  deletePar,
  downloadObject,
  formatSize,
  getBucketDetail,
  getLifecycle,
  getNamespace,
  listBuckets,
  listObjects,
  listPars,
  putLifecycle,
  setBucketVersioning,
  uploadObject,
  type BucketDetail,
  type BucketInfo,
  type LifecycleRule,
  type ObjectInfo,
  type PreauthRequest,
} from '../api/objectstorage';

const { Paragraph, Text } = Typography;

/** 对象存储浏览器：租户/compartment → Bucket 列表 → 对象列表（上传/下载/删除） */
export default function ObjectStorage() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number>();
  const [compartmentId, setCompartmentId] = useState('');
  const [namespace, setNamespace] = useState('');
  const [buckets, setBuckets] = useState<BucketInfo[]>([]);
  const [bucket, setBucket] = useState<string>();
  const [objects, setObjects] = useState<ObjectInfo[]>([]);
  const [prefix, setPrefix] = useState('');
  const [loadingBuckets, setLoadingBuckets] = useState(false);
  const [loadingObjects, setLoadingObjects] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm<{ name: string }>();

  // Bucket 管理抽屉（版本控制 / 生命周期 / 预签名 URL）
  const [manageName, setManageName] = useState<string | null>(null);
  const [bktDetail, setBktDetail] = useState<BucketDetail | null>(null);
  const [lcRules, setLcRules] = useState<LifecycleRule[]>([]);
  const [pars, setPars] = useState<PreauthRequest[]>([]);
  const [manageLoading, setManageLoading] = useState(false);
  const [ruleForm] = Form.useForm();

  // 分享对象（预签名 URL）
  const [shareObj, setShareObj] = useState<string | null>(null);
  const [shareForm] = Form.useForm();
  const [shareResult, setShareResult] = useState<PreauthRequest | null>(null);
  const [shareLoading, setShareLoading] = useState(false);

  // 租户列表
  useEffect(() => {
    listTenants()
      .then((ts) => {
        setTenants(ts);
        if (ts.length > 0) setTenantId(ts[0].id);
      })
      .catch(() => setTenants([]));
  }, []);

  const fetchBuckets = useCallback(async (tid: number, comp: string) => {
    setLoadingBuckets(true);
    try {
      const [ns, bs] = await Promise.all([
        getNamespace(tid),
        listBuckets(tid, comp.trim() || undefined),
      ]);
      setNamespace(ns);
      setBuckets(bs);
      setBucket((prev) => (prev && bs.some((b) => b.name === prev) ? prev : bs[0]?.name));
    } catch {
      setBuckets([]);
      setNamespace('');
    } finally {
      setLoadingBuckets(false);
    }
  }, []);

  const fetchObjects = useCallback(
    async (tid: number, ns: string, bkt: string, pfx: string) => {
      setLoadingObjects(true);
      try {
        setObjects(await listObjects(tid, ns, bkt, pfx.trim()));
      } catch {
        setObjects([]);
      } finally {
        setLoadingObjects(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (tenantId) fetchBuckets(tenantId, compartmentId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  useEffect(() => {
    if (tenantId && namespace && bucket) fetchObjects(tenantId, namespace, bucket, prefix);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bucket, namespace]);

  const doCreateBucket = async (values: { name: string }) => {
    if (!tenantId) return;
    try {
      await createBucket(tenantId, compartmentId.trim() || '', values.name.trim());
      message.success('Bucket 创建成功');
      setCreateOpen(false);
      form.resetFields();
      fetchBuckets(tenantId, compartmentId);
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  // ---------------- Bucket 管理（版本控制 / 生命周期 / 预签名 URL） ----------------

  const openManage = async (name: string) => {
    if (!tenantId) return;
    setManageName(name);
    setManageLoading(true);
    try {
      const [d, lc, ps] = await Promise.all([
        getBucketDetail(tenantId, namespace, name),
        getLifecycle(tenantId, namespace, name),
        listPars(tenantId, namespace, name),
      ]);
      setBktDetail(d);
      setLcRules(lc);
      setPars(ps);
    } catch {
      setBktDetail(null);
      setLcRules([]);
      setPars([]);
    } finally {
      setManageLoading(false);
    }
  };

  const refreshManage = () => {
    if (manageName) openManage(manageName);
  };

  const toggleVersioning = async (enabled: boolean) => {
    if (!tenantId || !manageName) return;
    try {
      await setBucketVersioning(tenantId, namespace, manageName, enabled);
      message.success(`版本控制已${enabled ? '开启' : '暂停'}`);
      refreshManage();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const addLifecycleRule = async () => {
    if (!tenantId || !manageName) return;
    const v = await ruleForm.validateFields();
    const rules = [...lcRules.map((r) => ({ name: r.name, action: r.action, prefix: r.prefix, days: r.time_amount })), {
      name: v.name?.trim() || `rule-${v.action.toLowerCase()}`,
      action: v.action,
      prefix: v.prefix?.trim() || '',
      days: v.days,
    }];
    try {
      await putLifecycle(tenantId, namespace, manageName, rules);
      message.success('生命周期规则已保存');
      ruleForm.resetFields();
      refreshManage();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const removeLifecycleRule = async (ruleName: string) => {
    if (!tenantId || !manageName) return;
    const rules = lcRules
      .filter((r) => r.name !== ruleName)
      .map((r) => ({ name: r.name, action: r.action, prefix: r.prefix, days: r.time_amount }));
    try {
      await putLifecycle(tenantId, namespace, manageName, rules);
      message.success('规则已删除');
      refreshManage();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const revokePar = async (parId: string) => {
    if (!tenantId || !manageName) return;
    try {
      await deletePar(tenantId, namespace, manageName, parId);
      message.success('预签名 URL 已吊销');
      refreshManage();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  // ---------------- 分享对象（生成预签名 URL） ----------------

  const submitShare = async () => {
    if (!tenantId || !bucket || !shareObj) return;
    const v = await shareForm.validateFields();
    setShareLoading(true);
    try {
      const par = await createPar(tenantId, namespace, bucket, shareObj, v.expires_hours, v.access_type);
      setShareResult(par);
      message.success('分享链接已生成');
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      setShareLoading(false);
    }
  };

  const closeShare = () => {
    setShareObj(null);
    setShareResult(null);
    shareForm.resetFields();
  };

  const doDeleteBucket = async (name: string) => {
    if (!tenantId) return;
    try {
      await deleteBucket(tenantId, namespace, name);
      message.success('Bucket 已删除');
      fetchBuckets(tenantId, compartmentId);
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const doDeleteObject = async (name: string) => {
    if (!tenantId || !bucket) return;
    try {
      await deleteObject(tenantId, namespace, bucket, name);
      message.success('对象已删除');
      fetchObjects(tenantId, namespace, bucket, prefix);
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const doDownload = async (name: string) => {
    if (!tenantId || !bucket) return;
    try {
      const { url, filename } = await downloadObject(tenantId, namespace, bucket, name);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const uploadProps: UploadProps = {
    showUploadList: false,
    beforeUpload: (file) => {
      if (!tenantId || !bucket) {
        message.warning('请先选择租户和 Bucket');
        return Upload.LIST_IGNORE;
      }
      if (file.size > 50 * 1024 * 1024) {
        message.error('文件过大：单文件上限 50MB');
        return Upload.LIST_IGNORE;
      }
      const hide = message.loading(`正在上传 ${file.name}…`, 0);
      uploadObject(tenantId, namespace, bucket, file as File, prefix.trim())
        .then(() => {
          message.success('上传成功');
          fetchObjects(tenantId, namespace, bucket, prefix);
        })
        .catch(() => {
          /* 错误已由拦截器提示 */
        })
        .finally(hide);
      return Upload.LIST_IGNORE;
    },
  };

  const bucketColumns: ColumnsType<BucketInfo> = [
    { title: 'Bucket 名称', dataIndex: 'name', key: 'name', ellipsis: true },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, r) => (
        <Space size="small">
          <Button type="link" size="small" icon={<SettingOutlined />} onClick={() => openManage(r.name)}>
            管理
          </Button>
          <Popconfirm
            title={`删除 Bucket「${r.name}」？`}
            description="Bucket 必须为空才能删除"
            onConfirm={() => doDeleteBucket(r.name)}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const objectColumns: ColumnsType<ObjectInfo> = [
    { title: '对象名', dataIndex: 'name', key: 'name', ellipsis: true },
    {
      title: '大小',
      dataIndex: 'size',
      key: 'size',
      width: 110,
      render: (v: number) => formatSize(v),
      sorter: (a, b) => a.size - b.size,
    },
    {
      title: '创建时间',
      dataIndex: 'time_created',
      key: 'time_created',
      width: 180,
      render: (v: string | null) => (v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_, r) => (
        <Space>
          <Button type="link" size="small" icon={<DownloadOutlined />} onClick={() => doDownload(r.name)}>
            下载
          </Button>
          <Button type="link" size="small" icon={<LinkOutlined />} onClick={() => setShareObj(r.name)}>
            分享
          </Button>
          <Popconfirm title={`删除对象「${r.name}」？`} onConfirm={() => doDeleteObject(r.name)}>
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
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            placeholder="选择租户"
            style={{ width: 220 }}
            value={tenantId}
            onChange={setTenantId}
            options={tenants.map((t) => ({ label: `${t.name}（${t.region}）`, value: t.id }))}
          />
          <Input
            placeholder="Compartment OCID（空=租户根）"
            style={{ width: 320 }}
            value={compartmentId}
            onChange={(e) => setCompartmentId(e.target.value)}
          />
          <Button
            icon={<ReloadOutlined />}
            onClick={() => tenantId && fetchBuckets(tenantId, compartmentId)}
            loading={loadingBuckets}
          >
            刷新
          </Button>
          {namespace && <span style={{ color: '#888' }}>namespace: {namespace}</span>}
        </Space>
      </Card>

      <Row gutter={16}>
        <Col xs={24} lg={9}>
          <Card
            title="Buckets"
            extra={
              <Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
                新建
              </Button>
            }
          >
            <Table<BucketInfo>
              rowKey="name"
              size="small"
              columns={bucketColumns}
              dataSource={buckets}
              loading={loadingBuckets}
              pagination={false}
              rowSelection={{
                type: 'radio',
                selectedRowKeys: bucket ? [bucket] : [],
                onChange: (keys) => setBucket(keys[0] as string),
              }}
              onRow={(r) => ({ onClick: () => setBucket(r.name) })}
              locale={{ emptyText: <Empty description="暂无 Bucket" /> }}
            />
          </Card>
        </Col>
        <Col xs={24} lg={15}>
          <Card
            title={bucket ? `对象列表 · ${bucket}` : '对象列表'}
            extra={
              <Space>
                <Input.Search
                  placeholder="前缀过滤"
                  allowClear
                  style={{ width: 200 }}
                  value={prefix}
                  onChange={(e) => setPrefix(e.target.value)}
                  onSearch={() =>
                    tenantId && namespace && bucket && fetchObjects(tenantId, namespace, bucket, prefix)
                  }
                />
                <Upload {...uploadProps}>
                  <Button type="primary" icon={<UploadOutlined />} disabled={!bucket}>
                    上传
                  </Button>
                </Upload>
              </Space>
            }
          >
            {!bucket ? (
              <Empty description="请先选择一个 Bucket" />
            ) : (
              <Table<ObjectInfo>
                rowKey="name"
                size="small"
                columns={objectColumns}
                dataSource={objects}
                loading={loadingObjects}
                pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 个对象` }}
              />
            )}
          </Card>
        </Col>
      </Row>

      <Modal title="新建 Bucket" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={() => form.submit()} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={doCreateBucket}>
          <Form.Item
            name="name"
            label="Bucket 名称"
            rules={[
              { required: true, message: '请输入名称' },
              { pattern: /^[a-z0-9._-]+$/, message: '仅允许小写字母、数字、._-' },
            ]}
          >
            <Input placeholder="如：my-backup" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Bucket 管理抽屉：版本控制 / 生命周期 / 预签名 URL */}
      <Drawer
        title={`Bucket 管理 · ${manageName || ''}`}
        open={!!manageName}
        onClose={() => setManageName(null)}
        width={620}
        destroyOnClose
      >
        {manageLoading ? (
          <Empty description="加载中…" />
        ) : (
          <>
            <Text strong>版本控制</Text>
            <div style={{ margin: '8px 0 4px' }}>
              <Space>
                <Switch
                  checked={bktDetail?.versioning === 'Enabled'}
                  onChange={toggleVersioning}
                  checkedChildren="开启"
                  unCheckedChildren="暂停"
                />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  开启后同一对象的历史版本都会保留（占用额外存储），当前：{bktDetail?.versioning || '-'}
                </Text>
              </Space>
            </div>

            <Divider />
            <Space style={{ marginBottom: 8 }}>
              <Text strong>生命周期规则</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>对象到期自动转低频存储（ARCHIVE）或删除（DELETE）</Text>
            </Space>
            <Table<LifecycleRule>
              rowKey="name" size="small" pagination={false} dataSource={lcRules}
              locale={{ emptyText: '暂无规则' }}
              columns={[
                { title: '规则名', dataIndex: 'name', key: 'name' },
                {
                  title: '动作', dataIndex: 'action', key: 'action',
                  render: (v: string) => <Tag color={v === 'DELETE' ? 'red' : 'blue'}>{v}</Tag>,
                },
                { title: '前缀', dataIndex: 'prefix', key: 'prefix', render: (v: string) => v || '（全部）' },
                { title: '天数', dataIndex: 'time_amount', key: 'days' },
                {
                  title: '', key: 'op', width: 60,
                  render: (_, r) => (
                    <Popconfirm title={`删除规则「${r.name}」？`} onConfirm={() => removeLifecycleRule(r.name)}>
                      <Button type="link" size="small" danger>删除</Button>
                    </Popconfirm>
                  ),
                },
              ]}
            />
            <Form form={ruleForm} layout="inline" style={{ marginTop: 12 }} initialValues={{ action: 'ARCHIVE', days: 30 }}>
              <Form.Item name="name" style={{ width: 130 }}><Input placeholder="规则名（可选）" /></Form.Item>
              <Form.Item name="action" style={{ width: 120 }}>
                <Select options={[{ value: 'ARCHIVE', label: '转低频存储' }, { value: 'DELETE', label: '删除' }]} />
              </Form.Item>
              <Form.Item name="prefix" style={{ width: 140 }}><Input placeholder="对象前缀（可选）" /></Form.Item>
              <Form.Item name="days" rules={[{ required: true }]} style={{ width: 90 }}>
                <InputNumber min={1} placeholder="天数" style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item>
                <Button type="dashed" icon={<PlusOutlined />} onClick={addLifecycleRule}>添加规则</Button>
              </Form.Item>
            </Form>

            <Divider />
            <Space style={{ marginBottom: 8 }}>
              <Text strong>预签名 URL</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>限时分享链接，吊销后立即失效</Text>
            </Space>
            <Table<PreauthRequest>
              rowKey="id" size="small" pagination={false} dataSource={pars}
              locale={{ emptyText: '暂无预签名 URL' }}
              columns={[
                { title: '对象', dataIndex: 'object_name', key: 'obj', ellipsis: true, render: (v: string | null) => v || '（整个 Bucket）' },
                { title: '权限', dataIndex: 'access_type', key: 'acc', width: 120 },
                {
                  title: '过期', dataIndex: 'time_expires', key: 'exp', width: 150,
                  render: (v: string | null) => (v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '-'),
                },
                {
                  title: '', key: 'op', width: 110,
                  render: (_, r) => (
                    <Space size="small">
                      <Paragraph copyable={{ text: r.url }} style={{ margin: 0 }}><span style={{ fontSize: 12, color: '#1677ff' }}>复制</span></Paragraph>
                      <Popconfirm title="吊销该链接？" onConfirm={() => revokePar(r.id)}>
                        <Button type="link" size="small" danger>吊销</Button>
                      </Popconfirm>
                    </Space>
                  ),
                },
              ]}
            />
          </>
        )}
      </Drawer>

      {/* 分享对象：生成预签名 URL */}
      <Modal
        title={`分享对象 · ${shareObj || ''}`}
        open={!!shareObj}
        onCancel={closeShare}
        footer={null}
        destroyOnClose
        width={600}
      >
        {!shareResult ? (
          <Form form={shareForm} layout="vertical" initialValues={{ expires_hours: 24, access_type: 'ObjectRead' }} onFinish={submitShare}>
            <Form.Item name="access_type" label="权限">
              <Select
                options={[
                  { value: 'ObjectRead', label: '只读（下载）' },
                  { value: 'ObjectWrite', label: '只写（上传覆盖）' },
                  { value: 'ObjectReadWrite', label: '读写' },
                ]}
              />
            </Form.Item>
            <Form.Item name="expires_hours" label="有效期（小时）" rules={[{ required: true }]}>
              <InputNumber min={1} max={24 * 365} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item>
              <Button type="primary" htmlType="submit" loading={shareLoading} block>生成分享链接</Button>
            </Form.Item>
          </Form>
        ) : (
          <>
            <Text type="secondary">链接有效期至 {shareResult.time_expires ? new Date(shareResult.time_expires).toLocaleString('zh-CN', { hour12: false }) : '-'}</Text>
            <Paragraph copyable={{ text: shareResult.url }} ellipsis={{ rows: 3, expandable: true }} style={{ marginTop: 8 }}>
              {shareResult.url}
            </Paragraph>
            <Button onClick={() => { setShareResult(null); }} block>再生成一个</Button>
          </>
        )}
      </Modal>
    </div>
  );
}
