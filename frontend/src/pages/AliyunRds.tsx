import { useCallback, useEffect, useState } from 'react';
import {
  Button, Card, Descriptions, Drawer, Empty, Select, Space, Table, Tabs, Tag, Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { listTenants, listTenantRegions, type CloudRegion, type TenantOption } from '../api/tenants';
import {
  getAliRdsInstance,
  listAliRdsAccounts,
  listAliRdsDatabases,
  listAliRdsInstances,
  type AliRdsAccount,
  type AliRdsDatabase,
  type AliRdsInstance,
} from '../api/aliyun';

const { Text } = Typography;

function statusColor(s: string): string {
  const v = (s || '').toLowerCase();
  if (v === 'running') return 'green';
  if (['creating', 'changing', 'restarting', 'upgrading', 'importing', 'migrating', 'transforming'].includes(v)) return 'processing';
  if (v === 'stopped') return 'default';
  if (['deleted', 'deleting', 'failed'].includes(v)) return 'red';
  return 'blue';
}

function fmtMemoryGB(mb: number | undefined): string {
  if (mb === undefined || mb === null) return '—';
  const gb = mb / 1024;
  return Number.isInteger(gb) ? `${gb} GB` : `${gb.toFixed(1)} GB`;
}

function engineLabel(r: AliRdsInstance): string {
  const e = r.engine || '';
  const v = r.engine_version || '';
  const name = e ? e.charAt(0).toUpperCase() + e.slice(1) : '';
  return [name, v].filter(Boolean).join(' ') || '—';
}

/** 阿里云 RDS 数据库：实例列表（只读）+ 详情抽屉（概览/数据库/账号） */
export default function AliyunRds() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number>();
  const [regions, setRegions] = useState<CloudRegion[]>([]);
  const [regionId, setRegionId] = useState<string>();
  const [list, setList] = useState<AliRdsInstance[]>([]);
  const [loading, setLoading] = useState(false);
  const [tenantsLoaded, setTenantsLoaded] = useState(false);

  // 详情抽屉
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detail, setDetail] = useState<AliRdsInstance | null>(null);
  const [databases, setDatabases] = useState<AliRdsDatabase[]>([]);
  const [accounts, setAccounts] = useState<AliRdsAccount[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    listTenants()
      .then((ts) => {
        const alis = ts.filter((t) => t.provider === 'aliyun');
        setTenants(alis);
        if (alis.length > 0) setTenantId(alis[0].id);
      })
      .catch(() => setTenants([]))
      .finally(() => setTenantsLoaded(true));
  }, []);

  useEffect(() => {
    if (tenantId === undefined) {
      setRegions([]);
      return;
    }
    listTenantRegions(tenantId)
      .then(setRegions)
      .catch(() => setRegions([]));
  }, [tenantId]);

  const fetchList = useCallback(async (tid: number, region?: string) => {
    setLoading(true);
    try {
      setList(await listAliRdsInstances(tid, region));
    } catch {
      setList([]);
      message.error('查询失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tenantId !== undefined) fetchList(tenantId, regionId);
  }, [tenantId, regionId, fetchList]);

  const openDetail = async (inst: AliRdsInstance) => {
    if (tenantId === undefined) return;
    setDrawerOpen(true);
    setDetailLoading(true);
    setDetail(null);
    setDatabases([]);
    setAccounts([]);
    try {
      const [d, dbs, accs] = await Promise.all([
        getAliRdsInstance(tenantId, inst.id, regionId),
        listAliRdsDatabases(tenantId, inst.id, regionId).catch(() => [] as AliRdsDatabase[]),
        listAliRdsAccounts(tenantId, inst.id, regionId).catch(() => [] as AliRdsAccount[]),
      ]);
      setDetail(d);
      setDatabases(dbs);
      setAccounts(accs);
    } catch {
      message.error('详情查询失败');
    } finally {
      setDetailLoading(false);
    }
  };

  const columns: ColumnsType<AliRdsInstance> = [
    {
      title: '实例名称', key: 'name', width: 220, ellipsis: true,
      render: (_, r) => (
        <div>
          <div><Text strong>{r.name || '—'}</Text></div>
          <Text type="secondary" copyable style={{ fontSize: 12 }}>{r.id}</Text>
        </div>
      ),
    },
    { title: '引擎版本', key: 'engine', width: 130, render: (_, r) => engineLabel(r) },
    { title: '规格', dataIndex: 'instance_class', key: 'class', width: 150, ellipsis: true, render: (v: string) => v || '—' },
    {
      title: '内存 / 存储', key: 'mem', width: 150,
      render: (_, r) => `${fmtMemoryGB(r.memory)} / ${r.storage ? `${r.storage} GB` : '—'}`,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 110,
      render: (v: string) => <Tag color={statusColor(v)}>{v || '—'}</Tag>,
    },
    {
      title: '连接地址', key: 'conn', width: 260, ellipsis: true,
      render: (_, r) =>
        r.connection ? (
          <Text copyable style={{ fontSize: 12 }}>{`${r.connection}${r.port ? `:${r.port}` : ''}`}</Text>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    { title: '创建时间', dataIndex: 'creation_time', key: 'created', width: 170, render: (v: string) => v || '—' },
    {
      title: '操作', key: 'op', width: 90, fixed: 'right',
      render: (_, r) => (
        <Button type="link" onClick={() => openDetail(r)}>
          详情
        </Button>
      ),
    },
  ];

  const dbColumns: ColumnsType<AliRdsDatabase> = [
    { title: '数据库名', dataIndex: 'name', key: 'name', ellipsis: true },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 110,
      render: (v: string) => <Tag color={v === 'Running' ? 'green' : 'blue'}>{v || '—'}</Tag>,
    },
    { title: '描述', dataIndex: 'description', key: 'desc', ellipsis: true, render: (v: string) => v || '—' },
  ];

  const accountColumns: ColumnsType<AliRdsAccount> = [
    { title: '账号名', dataIndex: 'name', key: 'name', ellipsis: true },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 110,
      render: (v: string) => <Tag color={v === 'Available' ? 'green' : 'blue'}>{v || '—'}</Tag>,
    },
    { title: '类型', dataIndex: 'type', key: 'type', width: 160, render: (v: string) => v || '—' },
  ];

  const renderOverview = () => {
    if (!detail) return <Empty description="暂无详情" />;
    const d = detail;
    const conn = [d.connection, d.port ? String(d.port) : ''].filter(Boolean).join(':');
    const sgIds = Array.isArray(d.security_group_ids) ? (d.security_group_ids as string[]).join(', ') : String(d.security_group_ids ?? '');
    return (
      <Descriptions column={1} bordered size="small">
        <Descriptions.Item label="实例名称">{d.name || '—'}</Descriptions.Item>
        <Descriptions.Item label="实例 ID"><Text copyable>{d.id}</Text></Descriptions.Item>
        <Descriptions.Item label="引擎版本">{engineLabel(d)}</Descriptions.Item>
        <Descriptions.Item label="规格">{d.instance_class || '—'}</Descriptions.Item>
        <Descriptions.Item label="内存">{fmtMemoryGB(d.memory)}</Descriptions.Item>
        <Descriptions.Item label="存储">{d.storage ? `${d.storage} GB` : '—'}</Descriptions.Item>
        <Descriptions.Item label="最大连接数">{String(d.max_connections ?? '—')}</Descriptions.Item>
        <Descriptions.Item label="可用区">{String(d.zone ?? d.zone_id ?? '—')}</Descriptions.Item>
        <Descriptions.Item label="VPC">{String(d.vpc_id ?? '—')}</Descriptions.Item>
        <Descriptions.Item label="交换机">{String(d.vswitch_id ?? '—')}</Descriptions.Item>
        <Descriptions.Item label="安全组">{sgIds || '—'}</Descriptions.Item>
        <Descriptions.Item label="连接地址">{conn ? <Text copyable>{conn}</Text> : '—'}</Descriptions.Item>
        <Descriptions.Item label="状态"><Tag color={statusColor(d.status)}>{d.status || '—'}</Tag></Descriptions.Item>
        <Descriptions.Item label="付费类型">{d.pay_type || '—'}</Descriptions.Item>
        <Descriptions.Item label="地域">{d.region || '—'}</Descriptions.Item>
        <Descriptions.Item label="创建时间">{d.creation_time || '—'}</Descriptions.Item>
      </Descriptions>
    );
  };

  if (tenantsLoaded && tenants.length === 0) {
    return (
      <Card title="RDS 数据库">
        <Empty description="还没有阿里云租户，请先添加" />
      </Card>
    );
  }

  return (
    <div>
      <Card
        title="RDS 数据库"
        extra={
          <Space wrap>
            <Select
              style={{ width: 220 }}
              placeholder="选择阿里云租户"
              value={tenantId}
              onChange={(v) => {
                setTenantId(v);
                setRegionId(undefined);
              }}
              options={tenants.map((t) => ({ value: t.id, label: t.name }))}
            />
            <Select
              style={{ width: 220 }}
              placeholder="地域（默认租户地域）"
              allowClear
              value={regionId}
              onChange={setRegionId}
              options={regions.map((r) => ({ value: r.id, label: `${r.name}（${r.id}）` }))}
              showSearch
              optionFilterProp="label"
            />
            <Button onClick={() => tenantId !== undefined && fetchList(tenantId, regionId)} loading={loading}>
              刷新
            </Button>
          </Space>
        }
      >
        <Table<AliRdsInstance>
          rowKey="id"
          columns={columns}
          dataSource={list}
          loading={loading}
          scroll={{ x: 1400 }}
          pagination={{ showSizeChanger: true, showTotal: (t) => `共 ${t} 个实例` }}
          locale={{ emptyText: '暂无 RDS 实例（该地域下没有实例或租户无 RDS 权限）' }}
          onRow={(r) => ({ onClick: () => openDetail(r), style: { cursor: 'pointer' } })}
        />
      </Card>

      <Drawer
        title={`RDS 实例详情${detail ? ` - ${detail.name || detail.id}` : ''}`}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={760}
        destroyOnClose
      >
        <Tabs
          defaultActiveKey="overview"
          items={[
            {
              key: 'overview',
              label: '概览',
              children: detailLoading ? <Empty description="加载中…" /> : renderOverview(),
            },
            {
              key: 'databases',
              label: `数据库（${databases.length}）`,
              children: (
                <Table<AliRdsDatabase>
                  rowKey="name"
                  columns={dbColumns}
                  dataSource={databases}
                  loading={detailLoading}
                  pagination={false}
                  size="small"
                  locale={{ emptyText: '该实例下暂无数据库' }}
                />
              ),
            },
            {
              key: 'accounts',
              label: `账号（${accounts.length}）`,
              children: (
                <Table<AliRdsAccount>
                  rowKey="name"
                  columns={accountColumns}
                  dataSource={accounts}
                  loading={detailLoading}
                  pagination={false}
                  size="small"
                  locale={{ emptyText: '该实例下暂无账号' }}
                />
              ),
            },
          ]}
        />
      </Drawer>
    </div>
  );
}
