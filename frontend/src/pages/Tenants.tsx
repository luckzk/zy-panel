import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import { PlusOutlined, QuestionCircleOutlined, SearchOutlined, UploadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { REGION_CN } from '../types';
import { getProviderMeta, providerOptions } from '../providers/registry';
import { getRegions } from '../api/meta';
import TenantApiGuide from '../components/TenantApiGuide';
import {
  batchCreateTenants,
  createTenant,
  deleteTenant,
  detectAccountType,
  getTenantList,
  testTenantConnection,
  updateTenant,
  type TenantCreateInput,
  type TenantDetail,
  type TenantUpdateInput,
} from '../api/tenants';

const { Text } = Typography;

/** 新建/编辑表单字段（与后端字段名一致） */
interface TenantFormValues {
  name: string;
  provider?: string;
  region: string;
  tenancy_ocid: string;
  user_ocid: string;
  fingerprint: string;
  private_key?: string;
  access_key_id?: string;
  access_key_secret?: string;
  aliyun_region?: string;
  access_key_id_masked?: string;
  account_type?: string;
}

/** 每行连接测试状态 */
type TestState = 'untested' | 'testing' | 'success' | 'error';

/** 租户配置页：真实接口联调（列表/新建/编辑/删除/连通性测试） */
export default function Tenants() {
  const [list, setList] = useState<TenantDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [regionFilter, setRegionFilter] = useState<string>();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<TenantDetail | null>(null);
  const [testState, setTestState] = useState<Record<number, { status: TestState; message?: string }>>({});
  const [form] = Form.useForm<TenantFormValues>();
  // Region 列表：后端 OCI SDK 权威来源（非写死）
  const [regionOptions, setRegionOptions] = useState<{ value: string; label: string }[]>([]);
  const [regionsLoading, setRegionsLoading] = useState(false);
  // 批量添加
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchText, setBatchText] = useState('');
  const [batchLoading, setBatchLoading] = useState(false);
  // API 密钥获取教程
  const [guideOpen, setGuideOpen] = useState(false);

  const batchTemplate = () => {
    setBatchText(
      JSON.stringify(
        [
          {
            name: '主账号-东京',
            region: 'ap-tokyo-1',
            tenancy_ocid: 'ocid1.tenancy.oc1..xxxx',
            user_ocid: 'ocid1.user.oc1..xxxx',
            fingerprint: 'aa:bb:cc:dd:ee:ff:00:11:22:33:44:55:66:77:88:99',
            private_key: '-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n',
          },
        ],
        null,
        2,
      ),
    );
  };

  const submitBatch = async () => {
    let arr: unknown;
    try {
      arr = JSON.parse(batchText);
    } catch {
      message.error('JSON 格式不正确，请检查');
      return;
    }
    if (!Array.isArray(arr) || arr.length === 0) {
      message.error('请提供非空的 JSON 数组');
      return;
    }
    setBatchLoading(true);
    try {
      const r = await batchCreateTenants(arr as TenantCreateInput[]);
      if (r.failed === 0) {
        message.success(`批量添加成功，共 ${r.success} 个租户`);
      } else {
        message.warning(`成功 ${r.success} 个，失败 ${r.failed} 个`);
        r.results.filter((x) => !x.ok).forEach((x) => message.error(`${x.name}：${x.error}`));
      }
      setBatchOpen(false);
      setBatchText('');
      fetchAll();
    } finally {
      setBatchLoading(false);
    }
  };

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      setList(await getTenantList());
    } catch {
      setList([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    // Region 下拉：走后端 /meta/regions（OCI SDK 列表），失败时留空并提示
    (async () => {
      setRegionsLoading(true);
      try {
        const rs = await getRegions();
        setRegionOptions(
          rs.map((r) => ({ value: r.id, label: REGION_CN[r.id] ? `${REGION_CN[r.id]} · ${r.id}` : r.id })),
        );
      } catch {
        message.error('Region 列表加载失败，请检查后端连接后重试');
      } finally {
        setRegionsLoading(false);
      }
    })();
  }, [fetchAll]);

  const filtered = useMemo(
    () =>
      list.filter(
        (t) =>
          (!keyword || t.name.includes(keyword) || t.tenancy_ocid.includes(keyword)) &&
          (!regionFilter || t.region === regionFilter),
      ),
    [list, keyword, regionFilter],
  );

  const openModal = (t?: TenantDetail) => {
    setEditing(t ?? null);
    form.setFieldsValue(
      t
        ? { name: t.name, provider: t.provider || 'oci', region: t.region, aliyun_region: t.region, tenancy_ocid: t.tenancy_ocid, user_ocid: t.user_ocid, fingerprint: t.fingerprint, private_key: '', access_key_id: '', access_key_secret: '', account_type: t.account_type || undefined }
        : ({ provider: 'oci', region: 'ap-tokyo-1' } as TenantFormValues),
    );
    setOpen(true);
  };

  const onFinish = async (values: TenantFormValues) => {
    try {
      if (editing) {
        const isAliyun = (editing.provider || 'oci') === 'aliyun';
        const body: TenantUpdateInput = {
          name: values.name,
          account_type: values.account_type || '',
        };
        if (isAliyun) {
          if (values.access_key_id?.trim()) body.access_key_id = values.access_key_id.trim();
          if (values.access_key_secret?.trim()) body.access_key_secret = values.access_key_secret.trim();
          if (values.aliyun_region?.trim()) body.aliyun_region = values.aliyun_region.trim();
        } else {
          Object.assign(body, {
            region: values.region,
            tenancy_ocid: values.tenancy_ocid,
            user_ocid: values.user_ocid,
            fingerprint: values.fingerprint,
          });
          if (values.private_key?.trim()) body.private_key = values.private_key.trim();
        }
        await updateTenant(editing.id, body);
        message.success('云账号已更新');
      } else {
        const provider = values.provider || 'oci';
        await createTenant({
          name: values.name,
          provider,
          region: values.region,
          tenancy_ocid: values.tenancy_ocid,
          user_ocid: values.user_ocid,
          fingerprint: values.fingerprint,
          private_key: (values.private_key || '').trim(),
          access_key_id: values.access_key_id?.trim(),
          access_key_secret: values.access_key_secret?.trim(),
          aliyun_region: values.aliyun_region || 'cn-hangzhou',
          account_type: values.account_type || '',
        });
        message.success('云账号已添加');
      }
      setOpen(false);
      form.resetFields();
      fetchAll();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const remove = async (id: number) => {
    try {
      await deleteTenant(id);
      message.success('已删除');
      fetchAll();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  /** 测试连接：调用真实 OCI 校验，行内展示结果 */
  const testConnection = async (record: TenantDetail) => {
    setTestState((prev) => ({ ...prev, [record.id]: { status: 'testing' } }));
    try {
      const result = await testTenantConnection(record.id);
      const ads = result.availability_domains.join(', ');
      setTestState((prev) => ({
        ...prev,
        [record.id]: { status: 'success', message: `可用域：${ads || '（无）'}` },
      }));
      message.success(`「${record.name}」连接正常`);
      fetchAll(); // 刷新列表，同步后端持久化的测试状态
    } catch {
      setTestState((prev) => ({ ...prev, [record.id]: { status: 'error', message: '连接失败，详见错误提示' } }));
    }
  };

  const renderStatus = (record: TenantDetail) => {
    // 本次正在测试 > 后端持久化状态 > 未测试
    const testing = testState[record.id]?.status === 'testing';
    const persisted = record.test_status;
    const st = testing ? 'testing' : persisted === 'success' ? 'success' : persisted === 'failed' ? 'error' : 'untested';
    const msg = testState[record.id]?.message
      ?? (record.last_tested_at ? `上次测试：${new Date(record.last_tested_at).toLocaleString('zh-CN', { hour12: false })}` : undefined);
    const tag =
      st === 'success' ? <Tag color="success">正常</Tag>
      : st === 'error' ? <Tag color="error">异常</Tag>
      : st === 'testing' ? <Tag color="processing">测试中</Tag>
      : <Tag color="default">未测试</Tag>;
    return msg ? <Tooltip title={msg}>{tag}</Tooltip> : tag;
  };

  const renderAccountType = (v: string) =>
    v === 'free' ? <Tag color="green">免费号</Tag>
    : v === 'paid' ? <Tag color="gold">付费号</Tag>
    : <Text type="secondary">未标记</Text>;

  /** 自动检测账号类型：启发式判断，结果自动写入 */
  const [detecting, setDetecting] = useState<Record<number, boolean>>({});
  /** 检测结果展示弹窗（声明式 Modal：antd 5.29 + React 19 下静态 Modal.info 不渲染） */
  const [detectResult, setDetectResult] = useState<{ name: string; label: string; reasons: string[] } | null>(null);
  const doDetect = async (record: TenantDetail) => {
    setDetecting((p) => ({ ...p, [record.id]: true }));
    try {
      const r = await detectAccountType(record.id);
      const label = r.detected === 'free' ? '免费号' : r.detected === 'paid' ? '付费号' : '未知';
      setDetectResult({ name: record.name, label, reasons: r.reasons });
      fetchAll();
    } finally {
      setDetecting((p) => ({ ...p, [record.id]: false }));
    }
  };

  const columns: ColumnsType<TenantDetail> = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 140 },
    {
      title: '云厂商',
      dataIndex: 'provider',
      key: 'provider',
      width: 110,
      render: (v: string) => {
        const meta = getProviderMeta(v);
        return <Tag color={meta.color}>{meta.short}</Tag>;
      },
    },
    {
      title: '地域',
      dataIndex: 'region',
      key: 'region',
      width: 140,
      render: (v: string) => <Tag color="blue">{v}</Tag>,
    },
    {
      title: '账号标识',
      dataIndex: 'tenancy_ocid',
      key: 'tenancy_ocid',
      width: 200,
      render: (v: string, r: TenantDetail) =>
        (r.provider || 'oci') === 'aliyun' ? (
          <Text copyable style={{ maxWidth: 220 }} ellipsis>
            {r.access_key_id_masked || '—'}
          </Text>
        ) : (
          <Text copyable style={{ maxWidth: 220 }} ellipsis>
            {v}
          </Text>
        ),
    },
    {
      title: 'User OCID',
      dataIndex: 'user_ocid',
      key: 'user_ocid',
      width: 200,
      render: (v: string, r: TenantDetail) =>
        (r.provider || 'oci') === 'aliyun' ? (
          <Text type="secondary">—</Text>
        ) : (
          <Text copyable style={{ maxWidth: 220 }} ellipsis>
            {v}
          </Text>
        ),
    },
    {
      title: 'Fingerprint',
      dataIndex: 'fingerprint',
      key: 'fingerprint',
      width: 180,
      ellipsis: true,
      render: (v: string, r: TenantDetail) => ((r.provider || 'oci') === 'aliyun' ? <Text type="secondary">—</Text> : v),
    },
    {
      title: '账号类型',
      dataIndex: 'account_type',
      key: 'account_type',
      width: 150,
      render: (v: string, record: TenantDetail) => (
        <Space size="small">
          {renderAccountType(v)}
          <Tooltip title="启发式自动检测（仅供参考）">
            <Button
              type="link"
              size="small"
              loading={!!detecting[record.id]}
              onClick={() => doDetect(record)}
            >
              检测
            </Button>
          </Tooltip>
        </Space>
      ),
    },
    {
      title: '状态',
      key: 'status',
      width: 90,
      render: (_, record) => renderStatus(record),
    },
    {
      title: '操作',
      key: 'action',
      width: 230,
      render: (_, record) => (
        <Space>
          <Button type="link" size="small" onClick={() => testConnection(record)}>
            测试连接
          </Button>
          <Button type="link" size="small" onClick={() => openModal(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除该租户配置吗？" onConfirm={() => remove(record.id)}>
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
      title="租户配置"
      extra={
        <Space>
          <Button onClick={fetchAll}>刷新</Button>
          <Button icon={<UploadOutlined />} onClick={() => setBatchOpen(true)}>
            批量添加
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>
            新建租户
          </Button>
        </Space>
      }
    >
      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          placeholder="搜索名称 / Tenancy OCID"
          prefix={<SearchOutlined />}
          allowClear
          style={{ width: 260 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <Select
          placeholder="Region 筛选"
          allowClear
          style={{ width: 180 }}
          value={regionFilter}
          onChange={setRegionFilter}
          options={regionOptions}
          loading={regionsLoading}
          showSearch
          optionFilterProp="label"
        />
      </Space>
      <Table<TenantDetail>
        rowKey="id"
        columns={columns}
        dataSource={filtered}
        loading={loading}
        scroll={{ x: 1200 }}
        pagination={{ showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
        locale={{ emptyText: '暂无租户配置，点击右上角「新建租户」添加' }}
      />
      <Modal
        title={
          <Space>
            {editing ? '编辑租户配置' : '新建租户配置'}
            <Tooltip title="如何获取 API 密钥？">
              <QuestionCircleOutlined
                style={{ color: '#1677ff', cursor: 'pointer' }}
                onClick={() => setGuideOpen(true)}
              />
            </Tooltip>
          </Space>
        }
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        destroyOnClose
        width={560}
      >
        <Form<TenantFormValues> form={form} layout="vertical" onFinish={onFinish}>
          <Form.Item name="name" label="配置名称" rules={[{ required: true, message: '请输入配置名称' }]}>
            <Input placeholder="如：主账号-东京" />
          </Form.Item>
          <Form.Item name="provider" label="云厂商" rules={[{ required: true }]}>
            <Select options={providerOptions()} disabled={!!editing} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev.provider !== cur.provider}>
            {({ getFieldValue }) => {
              const provider = getFieldValue('provider') || 'oci';
              if (provider === 'aliyun') {
                return (
                  <>
                    <Form.Item name="access_key_id" label="AccessKey ID" rules={[{ required: true, message: '请输入 AccessKey ID' }]}>
                      <Input placeholder="LTAI..." />
                    </Form.Item>
                    <Form.Item
                      name="access_key_secret"
                      label="AccessKey Secret"
                      rules={editing ? [] : [{ required: true, message: '请输入 AccessKey Secret' }]}
                      extra={editing ? '留空表示不更换密钥' : '密钥将加密存储，请勿泄露'}
                    >
                      <Input.Password placeholder="请输入 AccessKey Secret" />
                    </Form.Item>
                    <Form.Item name="aliyun_region" label="地域" rules={[{ required: true }]}>
                      <Input placeholder="如：cn-hangzhou（国内/国际靠地域区分）" />
                    </Form.Item>
                  </>
                );
              }
              return (
                <>
                  <Form.Item name="region" label="Region" rules={[{ required: true }]}>
                    <Select options={regionOptions} loading={regionsLoading} showSearch optionFilterProp="label" placeholder="搜索城市或 region，如：东京" />
                  </Form.Item>
                  <Form.Item name="tenancy_ocid" label="Tenancy OCID" rules={[{ required: true, message: '请输入 Tenancy OCID' }]}>
                    <Input placeholder="ocid1.tenancy.oc1..." />
                  </Form.Item>
                  <Form.Item name="user_ocid" label="User OCID" rules={[{ required: true, message: '请输入 User OCID' }]}>
                    <Input placeholder="ocid1.user.oc1..." />
                  </Form.Item>
                  <Form.Item name="fingerprint" label="API Key 指纹" rules={[{ required: true, message: '请输入指纹' }]}>
                    <Input placeholder="aa:bb:cc:..." />
                  </Form.Item>
                  <Form.Item
                    name="private_key"
                    label="Private Key（PEM）"
                    rules={editing ? [] : [{ required: true, message: '请粘贴私钥内容' }]}
                    extra={editing ? '留空表示不更换私钥' : '私钥将加密存储，请勿泄露'}
                  >
                    <Input.TextArea rows={4} placeholder="-----BEGIN PRIVATE KEY-----" />
                  </Form.Item>
                </>
              );
            }}
          </Form.Item>
          <Form.Item
            name="account_type"
            label="账号类型"
            tooltip="OCI 没有查询账号类型的 API，这里手动标记，用于区分免费号/付费号"
          >
            <Select
              allowClear
              placeholder="未标记"
              options={[
                { value: 'free', label: '免费号' },
                { value: 'paid', label: '付费号（升级号）' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="批量添加租户"
        open={batchOpen}
        onCancel={() => setBatchOpen(false)}
        onOk={submitBatch}
        confirmLoading={batchLoading}
        destroyOnClose
        width={640}
        okText="导入"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            粘贴 JSON 数组，每个元素包含 name / region / tenancy_ocid / user_ocid / fingerprint /
            private_key（PEM 全文，换行用 \n）。单次最多 50 个。
          </Text>
          <Button size="small" onClick={batchTemplate}>
            填入模板
          </Button>
          <Input.TextArea
            rows={12}
            value={batchText}
            onChange={(e) => setBatchText(e.target.value)}
            placeholder='[{"name":"...","region":"ap-tokyo-1",...}]'
            style={{ fontFamily: 'monospace', fontSize: 12 }}
          />
        </Space>
      </Modal>
      <Modal
        title={detectResult ? `「${detectResult.name}」检测结果：${detectResult.label}` : '检测结果'}
        open={detectResult !== null}
        onOk={() => setDetectResult(null)}
        onCancel={() => setDetectResult(null)}
        cancelText="关闭"
        width={520}
      >
        {detectResult && (
          <div>
            <p style={{ color: '#888' }}>启发式判断，仅供参考。如有误请手动修改。</p>
            <ul style={{ paddingLeft: 20, margin: 0 }}>
              {detectResult.reasons.map((x, i) => <li key={i} style={{ fontSize: 13 }}>{x}</li>)}
            </ul>
          </div>
        )}
      </Modal>
      <TenantApiGuide open={guideOpen} onClose={() => setGuideOpen(false)} />
    </Card>
  );
}
