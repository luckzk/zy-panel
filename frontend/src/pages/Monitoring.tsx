import { useCallback, useEffect, useMemo, useState } from 'react';
import { Card, Col, Empty, Progress, Row, Select, Space, Spin, Statistic } from 'antd';
import { ArrowDownOutlined, ArrowUpOutlined } from '@ant-design/icons';
import type { EChartsOption } from 'echarts';
import Chart from '../components/Chart';
import { listTenants, type TenantOption } from '../api/tenants';
import { listInstances } from '../api/instances';
import { getQuotas, getTraffic, type QuotaItem, type TrafficPoint } from '../api/monitoring';
import type { Instance } from '../types';

const HOURS_OPTIONS = [
  { label: '近 6 小时', value: 6 },
  { label: '近 24 小时', value: 24 },
  { label: '近 3 天', value: 72 },
  { label: '近 7 天', value: 168 },
];

/** 从实例列表估算某配额的已用量（limits API 只返回上限） */
function estimateUsed(name: string, instances: Instance[]): number | null {
  const n = name.toLowerCase();
  const running = instances.filter((i) => i.status === 'RUNNING');
  const ocpuSum = (list: Instance[]) => list.reduce((s, i) => s + (i.ocpus || 0), 0);
  if (n.includes('a1') && n.includes('core')) {
    return ocpuSum(running.filter((i) => i.shape.includes('A1.Flex')));
  }
  if (n.includes('e2') && n.includes('micro') && n.includes('core')) {
    return ocpuSum(running.filter((i) => i.shape.includes('E2.1.Micro') || i.shape.includes('E2.1')));
  }
  if ((n.includes('e2') || n.includes('e3') || n.includes('e4')) && n.includes('core') && n.includes('flex')) {
    return ocpuSum(running.filter((i) => i.shape.includes('Flex') && !i.shape.includes('A1.Flex')));
  }
  return null;
}

/** 流量监控页：真实 OCI 指标 + 配额 */
export default function Monitoring() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number>();
  const [instances, setInstances] = useState<Instance[]>([]);
  const [instanceId, setInstanceId] = useState<string>();
  const [hours, setHours] = useState(24);
  const [resolution, setResolution] = useState<'1m' | '5m' | '1h'>('1h');
  const [points, setPoints] = useState<TrafficPoint[]>([]);
  const [quotas, setQuotas] = useState<QuotaItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [quotaLoading, setQuotaLoading] = useState(false);

  // 租户列表
  useEffect(() => {
    listTenants().then((ts) => {
      setTenants(ts);
      if (ts.length > 0) setTenantId(ts[0].id);
    }).catch(() => setTenants([]));
  }, []);

  // 租户变化 -> 实例列表
  const tenantName = useMemo(() => tenants.find((t) => t.id === tenantId)?.name ?? '', [tenants, tenantId]);
  useEffect(() => {
    if (!tenantId) return;
    listInstances({ tenant_id: tenantId, page_size: 200 }, tenantName)
      .then(({ items }) => {
        setInstances(items);
        const first = items.find((i) => i.status === 'RUNNING') ?? items[0];
        setInstanceId(first?.id);
      })
      .catch(() => setInstances([]));
  }, [tenantId, tenantName]);

  // 流量 + 配额
  const fetchTraffic = useCallback(async () => {
    if (!tenantId) return;
    setLoading(true);
    try {
      const data = await getTraffic(tenantId, instanceId, hours, resolution);
      setPoints(data.points);
      if (!instanceId && data.instance_id) setInstanceId(data.instance_id);
    } catch {
      setPoints([]);
    } finally {
      setLoading(false);
    }
  }, [tenantId, instanceId, hours, resolution]);

  const fetchQuotas = useCallback(async () => {
    if (!tenantId) return;
    setQuotaLoading(true);
    try {
      setQuotas(await getQuotas(tenantId));
    } catch {
      setQuotas([]);
    } finally {
      setQuotaLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    fetchTraffic();
  }, [fetchTraffic]);
  useEffect(() => {
    fetchQuotas();
  }, [fetchQuotas]);

  const option = useMemo<EChartsOption>(
    () => ({
      tooltip: { trigger: 'axis' },
      legend: { data: ['入站', '出站'] },
      grid: { left: 48, right: 16, top: 40, bottom: 24 },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: points.map((p) => new Date(p.time).toLocaleString('zh-CN', { hour12: false })),
      },
      yAxis: { type: 'value', name: 'Mbps' },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 20 }],
      series: [
        {
          name: '入站', type: 'line', smooth: true, showSymbol: false,
          data: points.map((p) => p.inbound_mbps),
          lineStyle: { width: 2.5, color: '#2f6df6' },
          areaStyle: { opacity: 0.2, color: '#2f6df6' },
        },
        {
          name: '出站', type: 'line', smooth: true, showSymbol: false,
          data: points.map((p) => p.outbound_mbps),
          lineStyle: { width: 2.5, color: '#12b76a' },
          areaStyle: { opacity: 0.15, color: '#12b76a' },
        },
      ],
    }),
    [points],
  );

  const peakIn = useMemo(() => (points.length ? Math.max(...points.map((p) => p.inbound_mbps)) : 0), [points]);
  const totalOutGb = useMemo(
    () => (points.length ? points.reduce((s, p) => s + p.outbound_mbps, 0) * 3.6 / 8 / 1024 : 0),
    [points],
  );
  const currentIn = points.length ? points[points.length - 1].inbound_mbps : 0;

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            placeholder="选择租户"
            style={{ width: 200 }}
            value={tenantId}
            onChange={(v) => { setTenantId(v); setInstanceId(undefined); }}
            options={tenants.map((t) => ({ label: `${t.name}（${t.region}）`, value: t.id }))}
          />
          <Select
            placeholder="选择实例"
            allowClear
            style={{ width: 280 }}
            value={instanceId}
            onChange={setInstanceId}
            options={instances.map((i) => ({ label: `${i.name}（${i.publicIp || i.privateIp || '无IP'}）`, value: i.id }))}
          />
          <Select style={{ width: 140 }} value={hours} onChange={setHours} options={HOURS_OPTIONS} />
          <Select
            style={{ width: 120 }}
            value={resolution}
            onChange={(v) => {
              setResolution(v);
              // 分钟级粒度下自动收紧时间窗口
              if (v === '1m' && hours > 6) setHours(6);
              if (v === '5m' && hours > 48) setHours(24);
            }}
            options={[
              { label: '1 分钟', value: '1m' },
              { label: '5 分钟', value: '5m' },
              { label: '1 小时', value: '1h' },
            ]}
          />
        </Space>
      </Card>

      {tenants.length === 0 ? (
        <Card>
          <Empty description="还没有租户配置，请先到「租户配置」页添加 OCI 租户" />
        </Card>
      ) : (
        <>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col xs={24} sm={8}>
              <Card><Statistic title="入站峰值" value={peakIn} suffix="Mbps" precision={2} prefix={<ArrowDownOutlined />} /></Card>
            </Col>
            <Col xs={24} sm={8}>
              <Card><Statistic title="出站总量" value={totalOutGb} suffix="GB" precision={2} prefix={<ArrowUpOutlined />} /></Card>
            </Col>
            <Col xs={24} sm={8}>
              <Card><Statistic title="当前入站速率" value={currentIn} suffix="Mbps" precision={2} /></Card>
            </Col>
          </Row>

          <Card title="流量趋势（OCI Monitoring，1 小时粒度）" style={{ marginBottom: 16 }}>
            <Spin spinning={loading}>
              {points.length === 0 && !loading ? (
                <Empty description="暂无流量数据（实例可能刚创建，或该时段无指标）" />
              ) : (
                <Chart option={option} height={380} />
              )}
            </Spin>
          </Card>

          <Card title="Compute 配额（OCI Limits API）" extra={quotaLoading ? <Spin size="small" /> : null}>
            {quotas.length === 0 && !quotaLoading ? (
              <Empty description="暂无配额数据" />
            ) : (
              <Row gutter={[16, 16]}>
                {quotas.slice(0, 12).map((q) => {
                  const used = estimateUsed(q.name, instances);
                  const pct = used != null && q.value > 0 ? Math.min(100, Math.round((used / q.value) * 100)) : null;
                  return (
                    <Col key={q.name} xs={24} sm={12} md={8} lg={6}>
                      <Card size="small" title={q.name} style={{ borderRadius: 8 }}>
                        {pct != null ? (
                          <>
                            <div style={{ fontSize: 20, fontWeight: 600 }}>
                              {used}<span style={{ fontSize: 13, color: '#999' }}> / {q.value} OCPU</span>
                            </div>
                            <Progress percent={pct} strokeColor={pct > 80 ? '#ff4d4f' : '#2f6df6'} showInfo={false} />
                          </>
                        ) : (
                          <Statistic value={q.value} suffix="上限" />
                        )}
                      </Card>
                    </Col>
                  );
                })}
              </Row>
            )}
            {quotas.length > 12 && (
              <div style={{ marginTop: 12, color: '#999', fontSize: 12 }}>共 {quotas.length} 项配额，仅展示前 12 项</div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
