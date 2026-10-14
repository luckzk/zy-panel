import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Card, Col, Empty, Progress, Row, Select, Space, Statistic, Table, Tag } from 'antd';
import { DollarOutlined } from '@ant-design/icons';
import type { EChartsOption } from 'echarts';
import type { ColumnsType } from 'antd/es/table';
import Chart from '../components/Chart';
import { listTenants, type TenantOption } from '../api/tenants';
import { getBillingDetails, getBillingSummary, type BillingDetail, type BillingSummary } from '../api/billing';
import { getAliBilling, type AliBilling } from '../api/aliyun';
import { getProviderMeta } from '../providers/registry';

const DAYS_OPTIONS = [
  { label: '近 30 天', value: 30 },
  { label: '近 90 天', value: 90 },
];

const detailColumns: ColumnsType<BillingDetail> = [
  { title: '日期', dataIndex: 'time', key: 'time', width: 180, sorter: (a, b) => (a.time || '').localeCompare(b.time || ''), render: (v: string) => (v || '').slice(0, 10) },
  { title: '服务', dataIndex: 'service', key: 'service', width: 200, sorter: (a, b) => (a.service || '').localeCompare(b.service || '') },
  { title: '资源', dataIndex: 'resource_name', key: 'resource_name', width: 220, ellipsis: true, sorter: (a, b) => (a.resource_name || '').localeCompare(b.resource_name || '') },
  { title: '用量', dataIndex: 'quantity', key: 'quantity', width: 120, sorter: (a, b) => (a.quantity || 0) - (b.quantity || 0), render: (v: number) => Number(v).toFixed(2) },
  { title: '费用', dataIndex: 'amount', key: 'amount', width: 140, sorter: (a, b) => (a.amount || 0) - (b.amount || 0), render: (v: number, r) => `${Number(v).toFixed(4)} ${r.currency || ''}` },
];

/** 费用分析页：OCI 用量真实查询；阿里云走 BSS */
export default function Billing() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number>();
  const [days, setDays] = useState(30);
  const [summary, setSummary] = useState<BillingSummary | null>(null);
  const [details, setDetails] = useState<BillingDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  const tenant = tenants.find((t) => t.id === tenantId);
  const isAliyun = (tenant?.provider || 'oci') === 'aliyun';

  useEffect(() => {
    listTenants()
      .then((ts) => {
        setTenants(ts);
        if (ts.length > 0) setTenantId(ts[0].id);
      })
      .catch(() => setTenants([]));
  }, []);

  const fetchAll = useCallback(async () => {
    if (!tenantId) return;
    setLoading(true);
    setFailed(false);
    try {
      const [s, d] = await Promise.all([getBillingSummary(tenantId, days), getBillingDetails(tenantId, days)]);
      setSummary(s);
      setDetails(d);
    } catch {
      setFailed(true);
      setSummary(null);
      setDetails([]);
    } finally {
      setLoading(false);
    }
  }, [tenantId, days]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const dailyOption = useMemo<EChartsOption>(() => {
    const data = summary?.daily ?? [];
    return {
      tooltip: { trigger: 'axis', valueFormatter: (v) => `${v} ${summary?.currency ?? ''}` },
      grid: { left: 56, right: 16, top: 32, bottom: 24 },
      xAxis: { type: 'category', boundaryGap: false, data: data.map((d) => d.date) },
      yAxis: { type: 'value', name: summary?.currency || '' },
      series: [
        {
          name: '费用',
          type: 'line',
          smooth: true,
          showSymbol: false,
          data: data.map((d) => d.amount),
          lineStyle: { width: 2.5, color: '#7a5af8' },
          areaStyle: {
            opacity: 0.25,
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [{ offset: 0, color: '#7a5af8' }, { offset: 1, color: 'rgba(122,90,248,0)' }],
            },
          },
        },
      ],
    };
  }, [summary]);

  const avgDaily = summary && summary.days > 0 ? summary.total / summary.days : 0;

  const serviceColumns: ColumnsType<{ name: string; amount: number }> = useMemo(
    () => [
      { title: '服务', dataIndex: 'name', key: 'name' },
      {
        title: '费用',
        dataIndex: 'amount',
        key: 'amount',
        width: 200,
        render: (v: number) => `${v.toFixed(4)} ${summary?.currency ?? ''}`,
        sorter: (a, b) => a.amount - b.amount,
      },
      {
        title: '占比',
        key: 'share',
        width: 260,
        render: (_, r) => {
          const pct = summary && summary.total > 0 ? Math.round((r.amount / summary.total) * 100) : 0;
          return <Progress percent={pct} size="small" />;
        },
      },
    ],
    [summary],
  );

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <span>租户</span>
          <Select
            style={{ width: 260 }}
            placeholder="请选择租户"
            value={tenantId}
            onChange={setTenantId}
            options={tenants.map((t) => ({ label: `${t.name}（${t.region}）`, value: t.id }))}
          />
          <Select style={{ width: 140 }} value={days} onChange={setDays} options={DAYS_OPTIONS} />
          <Button type="primary" onClick={fetchAll} loading={loading}>
            查询
          </Button>
        </Space>
      </Card>

      {!tenantId ? (
        <Card>
          <Empty description="请先在租户配置中添加租户" />
        </Card>
      ) : isAliyun ? (
        <AliyunBillingView tenantId={tenantId} />
      ) : failed ? (
        <Card>
          <Empty
            description="费用数据获取失败：请确认该租户的 API 密钥有用量查询权限，且租户已产生用量（OCI 用量数据通常有数小时延迟）"
          />
        </Card>
      ) : (
        <>
          <Row gutter={16}>
            <Col xs={24} sm={8}>
              <Card>
                <Statistic
                  title={`近 ${days} 天总费用`}
                  value={summary?.total ?? 0}
                  precision={4}
                  prefix={<DollarOutlined />}
                  suffix={summary?.currency}
                  loading={loading}
                />
              </Card>
            </Col>
            <Col xs={24} sm={8}>
              <Card>
                <Statistic title="日均费用" value={avgDaily} precision={4} suffix={summary?.currency} loading={loading} />
              </Card>
            </Col>
            <Col xs={24} sm={8}>
              <Card>
                <Statistic title="涉及服务" value={summary?.by_service.length ?? 0} loading={loading} />
              </Card>
            </Col>
          </Row>

          <Card title="每日费用趋势" style={{ marginTop: 16 }}>
            {summary && summary.daily.length > 0 ? (
              <Chart option={dailyOption} height={300} />
            ) : (
              <Empty description={loading ? '加载中…' : '暂无用量数据（免费套餐未超额时费用可能为 0）'} />
            )}
          </Card>

          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col xs={24} lg={12}>
              <Card title="按服务分组">
                <Table
                  rowKey="name"
                  columns={serviceColumns}
                  dataSource={summary?.by_service ?? []}
                  loading={loading}
                  pagination={false}
                  size="small"
                />
              </Card>
            </Col>
            <Col xs={24} lg={12}>
              <Card title="费用明细">
                <Table
                  rowKey={(r) => `${r.time}-${r.resource_id}-${r.service}`}
                  columns={detailColumns}
                  dataSource={details}
                  loading={loading}
                  pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 条` }}
                  size="small"
                  scroll={{ y: 380 }}
                />
              </Card>
            </Col>
          </Row>
        </>
      )}
    </div>
  );
}

/** 阿里云费用视图：BSS 余额 + 当月账单 */
function AliyunBillingView({ tenantId }: { tenantId: number }) {
  const [data, setData] = useState<AliBilling | null>(null);
  const [loading, setLoading] = useState(false);
  const [errMsg, setErrMsg] = useState('');
  const meta = getProviderMeta('aliyun');

  const fetch = useCallback(async () => {
    setLoading(true);
    setErrMsg('');
    try {
      setData(await getAliBilling(tenantId));
    } catch (e) {
      setErrMsg(e instanceof Error ? e.message : '查询失败');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => { fetch(); }, [fetch]);

  const prodColumns: ColumnsType<{ product: string; amount: number; currency: string }> = [
    { title: '产品', dataIndex: 'product', key: 'product' },
    {
      title: '金额', dataIndex: 'amount', key: 'amount', width: 160, sorter: (a, b) => a.amount - b.amount,
      render: (v: number, r) => `${v.toFixed(2)} ${r.currency}`,
    },
  ];

  return (
    <div>
      <Row gutter={16}>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic
              title={<Space>账户可用余额 <Tag color={meta.color}>{meta.short}</Tag></Space>}
              value={data?.balance.available_amount ?? '-'}
              suffix={data?.balance.currency}
              loading={loading}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic
              title={`本月账单（${data?.bill.billing_cycle || '-'}）`}
              value={data?.bill.total ?? 0}
              precision={2}
              suffix="CNY"
              loading={loading}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic
              title="涉及产品"
              value={data?.bill.products.length ?? 0}
              loading={loading}
            />
          </Card>
        </Col>
      </Row>
      <Card title="按产品分组" style={{ marginTop: 16 }} extra={<Button size="small" loading={loading} onClick={fetch}>刷新</Button>}>
        {errMsg ? (
          <Empty description={`查询失败：${errMsg}（部分国际版账号 BSS 接口权限受限）`} />
        ) : (
          <Table
            rowKey="product_code"
            columns={prodColumns}
            dataSource={data?.bill.products ?? []}
            loading={loading}
            pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 项` }}
            size="small"
          />
        )}
      </Card>
    </div>
  );
}
