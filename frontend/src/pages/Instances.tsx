import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
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
import { Link, useNavigate } from 'react-router-dom';
import {
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SearchOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { Instance, InstanceStatus } from '../types';
import { getShapes, type Shape as ShapeMeta } from '../api/meta';
import { listTenants, listTenantRegions, type CloudRegion, type TenantOption } from '../api/tenants';
import { getProviderMeta } from '../providers/registry';
import {
  changeShape,
  listInstances,
  powerInstance,
  renameInstance,
  terminateInstance,
  type PowerOp,
} from '../api/instances';

const { Text } = Typography;

/** 实例状态标签颜色 */
const STATUS_COLOR: Record<InstanceStatus, string> = {
  RUNNING: 'success',
  STOPPED: 'error',
  STARTING: 'processing',
  STOPPING: 'warning',
  TERMINATED: 'default',
};

const STATUS_TEXT: Record<InstanceStatus, string> = {
  RUNNING: '运行中',
  STOPPED: '已停止',
  STARTING: '启动中',
  STOPPING: '停止中',
  TERMINATED: '已终止',
};

const POWER_LABEL: Record<PowerOp, string> = { start: '启动', stop: '停止', reboot: '重启' };

/** 实例管理页：实例表格 + 真实电源操作/改名/终止 + 详情抽屉 */
export default function Instances() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number>();
  const [list, setList] = useState<Instance[]>([]);
  const [loading, setLoading] = useState(false);
  const [tenantsLoaded, setTenantsLoaded] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [statusFilter, setStatusFilter] = useState<InstanceStatus>();
  // 阿里云地域选择（租户默认地域为初始值）
  const [regionId, setRegionId] = useState<string>();
  const [regionOptions, setRegionOptions] = useState<CloudRegion[]>([]);
  const [regionLoading, setRegionLoading] = useState(false);
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [opLoading, setOpLoading] = useState(false);
  const navigate = useNavigate();

  /** 打开详情（整页） */
  const openDetail = (record: Instance) => {
    if (tenantId === undefined) return;
    const provider = record.provider || 'oci';
    navigate(`/instances/${encodeURIComponent(record.id)}?tenant_id=${tenantId}&provider=${provider}`);
  };

  // 改名弹窗
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<Instance | null>(null);
  const [newName, setNewName] = useState('');
  const [renameLoading, setRenameLoading] = useState(false);

  // 改 Shape 弹窗
  const [shapeOpen, setShapeOpen] = useState(false);
  const [shapeTarget, setShapeTarget] = useState<Instance | null>(null);
  const [shapeForm] = Form.useForm();
  const [shapeLoading, setShapeLoading] = useState(false);
  const shapeValue = Form.useWatch('shape', shapeForm);
  const isFlexShape = (shapeValue ?? '').includes('Flex');
  // 改 Shape 可选列表：实时从 OCI 拉取（非写死）
  const [shapeOptions, setShapeOptions] = useState<ShapeMeta[]>([]);
  const [shapeOptionsLoading, setShapeOptionsLoading] = useState(false);

  /** 加载租户列表，默认选中第一个 */
  useEffect(() => {
    listTenants()
      .then((ts) => {
        setTenants(ts);
        if (ts.length > 0) setTenantId(ts[0].id);
      })
      .catch(() => message.error('租户列表加载失败'))
      .finally(() => setTenantsLoaded(true));
  }, []);

  /** 按租户拉取实例列表（regionId 仅阿里云有效，不传则用租户默认地域） */
  const fetchInstances = useCallback(async (tid: number, tname: string, region?: string) => {
    setLoading(true);
    try {
      // 个人面板实例数有限，一次拉 200 条，前端做筛选
      const { items } = await listInstances({ tenant_id: tid, page_size: 200, region_id: region }, tname);
      setList(items);
    } catch {
      setList([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const refresh = useCallback(() => {
    if (tenantId === undefined) return;
    const t = tenants.find((x) => x.id === tenantId);
    fetchInstances(tenantId, t?.name ?? '', t?.provider === 'aliyun' ? regionId : undefined);
    setSelectedKeys([]);
  }, [tenantId, tenants, fetchInstances, regionId]);

  /** 租户切换：阿里云租户拉取地域列表并默认选中租户地域 */
  useEffect(() => {
    if (tenantId === undefined) return;
    const t = tenants.find((x) => x.id === tenantId);
    setSelectedKeys([]);
    if (t?.provider === 'aliyun') {
      setRegionLoading(true);
      listTenantRegions(tenantId)
        .then((rs) => {
          setRegionOptions(rs);
          const def = t.region || rs[0]?.id;
          setRegionId(def);
          fetchInstances(tenantId, t.name, def);
        })
        .catch(() => {
          setRegionOptions([]);
          fetchInstances(tenantId, t.name, t.region || undefined);
        })
        .finally(() => setRegionLoading(false));
    } else {
      setRegionOptions([]);
      setRegionId(undefined);
      fetchInstances(tenantId, t?.name ?? '');
    }
  }, [tenantId, tenants, fetchInstances]);

  const filtered = useMemo(
    () =>
      list.filter(
        (i) =>
          (!keyword || i.name.includes(keyword) || i.publicIp.includes(keyword)) &&
          (!statusFilter || i.status === statusFilter),
      ),
    [list, keyword, statusFilter],
  );

  /** 电源操作（真实接口，支持批量） */
  const powerOp = async (ids: React.Key[], action: PowerOp) => {
    if (tenantId === undefined) return;
    setOpLoading(true);
    let okCount = 0;
    try {
      for (const id of ids) {
        try {
          await powerInstance(tenantId, String(id), action);
          okCount++;
        } catch {
          /* 单台失败已由拦截器提示，继续处理其余 */
        }
      }
      const fail = ids.length - okCount;
      if (fail === 0) message.success(`${POWER_LABEL[action]}指令已发送（${okCount} 台）`);
      else message.warning(`${POWER_LABEL[action]}完成：${okCount} 成功 / ${fail} 失败`);
    } finally {
      setOpLoading(false);
      refresh();
    }
  };

  /** 终止实例（Popconfirm 二次确认已在外层完成） */
  const terminate = async (id: string) => {
    if (tenantId === undefined) return;
    setOpLoading(true);
    try {
      await terminateInstance(tenantId, id, true);
      message.success('终止指令已发送，引导卷已保留');
    } finally {
      setOpLoading(false);
      refresh();
    }
  };



  /** 改名提交 */
  const submitRename = async () => {
    if (!renameTarget || tenantId === undefined) return;
    const name = newName.trim();
    if (!name) {
      message.warning('请输入新的实例名称');
      return;
    }
    setRenameLoading(true);
    try {
      await renameInstance(tenantId, renameTarget.id, name);
      message.success('实例名称已更新');
      setRenameOpen(false);
      refresh();
    } finally {
      setRenameLoading(false);
    }
  };

  /** 打开改 Shape 弹窗：实时拉取该租户可用 Shape */
  const openShape = (record: Instance) => {
    setShapeTarget(record);
    shapeForm.setFieldsValue({ shape: record.shape, ocpus: undefined, memory_in_gbs: undefined });
    setShapeOpen(true);
    if (tenantId === undefined) return;
    setShapeOptionsLoading(true);
    getShapes(tenantId)
      .then(setShapeOptions)
      .catch(() => message.error('Shape 列表加载失败，请检查租户连通性'))
      .finally(() => setShapeOptionsLoading(false));
  };

  /** 改 Shape 提交 */
  const submitShape = async () => {
    if (!shapeTarget || tenantId === undefined) return;
    try {
      const values = await shapeForm.validateFields();
      setShapeLoading(true);
      await changeShape(tenantId, shapeTarget.id, {
        shape: values.shape,
        ocpus: values.ocpus ?? null,
        memory_in_gbs: values.memory_in_gbs ?? null,
      });
      message.success('Shape 已更新，实例启动后生效');
      setShapeOpen(false);
      refresh();
    } finally {
      setShapeLoading(false);
    }
  };

  const columns: ColumnsType<Instance> = [
    {
      title: '实例名称',
      dataIndex: 'name',
      key: 'name',
      width: 150,
      render: (v: string, record) => (
        <a onClick={() => openDetail(record)}>{v}</a>
      ),
    },
    {
      title: 'OCID',
      dataIndex: 'ocid',
      key: 'ocid',
      render: (v: string) => (
        <Text copyable style={{ maxWidth: 200 }} ellipsis>
          {v}
        </Text>
      ),
    },
    { title: '租户', dataIndex: 'tenant', key: 'tenant', width: 120 },
    {
      title: '云厂商',
      dataIndex: 'provider',
      key: 'provider',
      width: 90,
      render: (v: string | undefined) => {
        const meta = getProviderMeta(v);
        return <Tag color={meta.color}>{meta.short}</Tag>;
      },
    },
    { title: '可用域', dataIndex: 'ad', key: 'ad', width: 160 },
    { title: 'Shape', dataIndex: 'shape', key: 'shape', width: 170 },
    {
      title: '配置',
      key: 'spec',
      width: 110,
      render: (_, r) =>
        r.ocpus > 0 && r.memoryGb > 0 ? (
          <Text strong>{`${r.ocpus}C / ${r.memoryGb}G`}</Text>
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
    { title: '公网 IP', dataIndex: 'publicIp', key: 'publicIp', width: 130 },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v: InstanceStatus) => <Tag color={STATUS_COLOR[v]}>{STATUS_TEXT[v]}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 280,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          <Tooltip title="详情">
            <Button type="text" size="small" icon={<EyeOutlined />} onClick={() => openDetail(record)} />
          </Tooltip>
          <Tooltip title="启动">
            <Button type="text" size="small" icon={<PlayCircleOutlined />} loading={opLoading} onClick={() => powerOp([record.id], 'start')} />
          </Tooltip>
          <Tooltip title="停止">
            <Button type="text" size="small" icon={<PauseCircleOutlined />} loading={opLoading} onClick={() => powerOp([record.id], 'stop')} />
          </Tooltip>
          <Tooltip title="重启">
            <Button type="text" size="small" icon={<ReloadOutlined />} loading={opLoading} onClick={() => powerOp([record.id], 'reboot')} />
          </Tooltip>
          <Tooltip title="改名">
            <Button
              type="text"
              size="small"
              icon={<EditOutlined />}
              onClick={() => {
                setRenameTarget(record);
                setNewName(record.name);
                setRenameOpen(true);
              }}
            />
          </Tooltip>
          <Tooltip title="改配置（Shape）">
            <Button type="text" size="small" icon={<SettingOutlined />} onClick={() => openShape(record)} />
          </Tooltip>
          <Popconfirm
            title="确定终止该实例吗？此操作不可恢复！"
            description="引导卷将保留，可用于救援数据。"
            onConfirm={() => terminate(record.id)}
          >
            <Tooltip title="终止实例">
              <Button type="text" size="small" danger icon={<DeleteOutlined />} loading={opLoading} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  if (tenantsLoaded && tenants.length === 0) {
    return (
      <Card title="实例管理">
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
      title="实例管理"
      extra={
        <Button onClick={refresh} loading={loading}>
          刷新
        </Button>
      }
    >
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          placeholder="选择租户"
          style={{ width: 200 }}
          value={tenantId}
          onChange={setTenantId}
          options={tenants.map((t) => ({ value: t.id, label: `${t.name}（${t.region}）` }))}
        />
        {tenants.find((t) => t.id === tenantId)?.provider === 'aliyun' && (
          <Select
            placeholder="选择地域"
            style={{ width: 220 }}
            value={regionId}
            loading={regionLoading}
            onChange={(v) => {
              setRegionId(v);
              const t = tenants.find((x) => x.id === tenantId);
              if (tenantId !== undefined) fetchInstances(tenantId, t?.name ?? '', v);
              setSelectedKeys([]);
            }}
            options={regionOptions.map((r) => ({ value: r.id, label: r.name ? `${r.name}（${r.id}）` : r.id }))}
          />
        )}
        <Input
          placeholder="搜索名称 / 公网 IP"
          prefix={<SearchOutlined />}
          allowClear
          style={{ width: 240 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <Select
          placeholder="状态筛选"
          allowClear
          style={{ width: 140 }}
          value={statusFilter}
          onChange={setStatusFilter}
          options={Object.entries(STATUS_TEXT).map(([value, label]) => ({ value, label }))}
        />
        <Button disabled={!selectedKeys.length} loading={opLoading} onClick={() => powerOp(selectedKeys, 'start')}>
          批量启动
        </Button>
        <Button disabled={!selectedKeys.length} loading={opLoading} onClick={() => powerOp(selectedKeys, 'stop')}>
          批量停止
        </Button>
        <Button disabled={!selectedKeys.length} loading={opLoading} onClick={() => powerOp(selectedKeys, 'reboot')}>
          批量重启
        </Button>
      </Space>
      <Table<Instance>
        rowKey="id"
        columns={columns}
        dataSource={filtered}
        loading={loading}
        scroll={{ x: 1600 }}
        rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
        pagination={{ showSizeChanger: true, showTotal: (t) => `共 ${t} 台` }}
      />

      {/* 实例详情弹窗 */}


      {/* 改名弹窗 */}
      <Modal
        title={`修改实例名称`}
        open={renameOpen}
        onCancel={() => setRenameOpen(false)}
        onOk={submitRename}
        confirmLoading={renameLoading}
        destroyOnClose
      >
        <Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="输入新的实例显示名" maxLength={255} />
      </Modal>

      {/* 改 Shape 弹窗 */}
      <Modal
        title={`更改实例配置${shapeTarget ? `（${shapeTarget.name}）` : ''}`}
        open={shapeOpen}
        onCancel={() => setShapeOpen(false)}
        onOk={submitShape}
        confirmLoading={shapeLoading}
        destroyOnClose
        width={520}
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="实例必须处于关机状态才能更改 Shape"
          description="如果实例正在运行，请先执行「停止」操作。更改后下次启动生效。"
        />
        <Form form={shapeForm} layout="vertical" preserve={false}>
          <Form.Item name="shape" label="目标 Shape" rules={[{ required: true, message: '请选择 Shape' }]}>
            <Select
              loading={shapeOptionsLoading}
              showSearch
              optionFilterProp="label"
              placeholder="从 OCI 实时获取"
              options={shapeOptions.map((s) => ({
                value: s.shape,
                label: s.is_flex && s.ocpus ? `${s.shape}（${s.ocpus} OCPU / ${s.memory_in_gbs} GB）` : s.shape,
              }))}
            />
          </Form.Item>
          {isFlexShape && (
            <>
              <Form.Item name="ocpus" label="OCPU 数" rules={[{ required: true, message: 'Flex 机型必填' }]}>
                <InputNumber min={1} max={64} style={{ width: '100%' }} placeholder="如：4" />
              </Form.Item>
              <Form.Item name="memory_in_gbs" label="内存（GB）" rules={[{ required: true, message: 'Flex 机型必填' }]}>
                <InputNumber min={1} max={1024} style={{ width: '100%' }} placeholder="如：24" />
              </Form.Item>
            </>
          )}
        </Form>
      </Modal>
    </Card>
  );
}
