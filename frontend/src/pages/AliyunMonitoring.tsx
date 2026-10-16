import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Card, Col, Empty, Row, Select, Space, Spin, Statistic } from 'antd';
import { ArrowDownOutlined, ArrowUpOutlined, ReloadOutlined } from '@ant-design/icons';
import type { EChartsOption } from 'echarts';
import Chart from '../components/Chart';
import { listTenants, listTenantRegions, type TenantOption } from '../api/tenants';
import { getAliMonitoringOverview, type AliMonitoringOverview } from '../api/aliyun';

const HOURS_OPTIONS = [
  { label: '近 1 小时', value: 1 },
  { label: '近 6 小时', value: 6 },
  { label: '近 24 小时', value: 24 },
];

const BPS_TO_MBPS = 1 / 1_000_000;

const fmtTime = (t: string) => new Date(t).toLocaleString('zh-CN', { hour12: false });

/** 按 time 字符串对齐求和：返回 [时间, x轴标签, 聚合值] */
function aggregate(
  seriesList: { points: { time: string; value: number }[] }[],
): { times: string[]; values: number[] } {
  const map = new Map<string, number>();
  for (const s of seriesList) {
    for (const p of s.points) {
      map.set(p.time, (map.get(p.time) ?? 0) + p.value);
    }
  }
  const times = [...map.keys()].sort();
  return { times, values: times.map((t) => map.get(t) ?? 0) };
}

/** 阿里云全局流量监控：多实例公网带宽聚合 + CPU 曲线 */
export default function AliyunMonitoring() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number>();
  const [regions, setRegions] = useState<{ label: string; value: string }[]>([]);
  const [regionId, setRegionId] = useState<string>();
  const [hours, setHours] = useState(6);
  const [data, setData] = useState<AliMonitoringOverview | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  // 阿里云租户列表
  useEffect(() => {
    listTenants()
      .then((ts) => {
        const ali = ts.filter((t) => t.provider === 'aliyun');
        setTenants(ali);
        if (ali.length > 0) setTenantId(ali[0].id);
      })
      .catch(() => setTenants([]));
  }, []);

  // 租户变化 -> 地域列表
  useEffect(() => {
    if (!tenantId) return;
    listTenantRegions(tenantId)
      .then((rs) => setRegions(rs.map((r) => ({ label: `${r.name}（${r.id}）`, value: r.id }))))
      .catch(() => setRegions([]));
  }, [tenantId]);

  const fetchData = useCallback(async () => {
    if (!tenantId) return;
    setLoading(true);
    try {
      const d = await getAliMonitoringOverview(tenantId, regionId, hours);
      setData(d);
      setSelectedIds(d.instances.map((i) => i.instance_id));
    } catch {
      setData(null);
      setSelectedIds([]);
    } finally {
      setLoading(false);
    }
  }, [tenantId, regionId, hours]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const instances = data?.instances ?? [];
  const selected = useMemo(
    () => instances.filter((i) => selectedIds.includes(i.instance_id)),
    [instances, selectedIds],
  );

  const metricOf = (inst: { metrics: { metric: string; points: { time: string; value: number }[] }[] }, code: string) =>
    inst.metrics.find((m) => m.metric === code);

  // 公网入/出聚合
  const bwIn = useMemo(
    () => aggregate(selected.map((i) => metricOf(i, 'internet_in') ?? { points: [] })),
    [selected],
  );
  const bwOut = useMemo(
    () => aggregate(selected.map((i) => metricOf(i, 'internet_out') ?? { points: [] })),
    [selected],
  );
  const times = useMemo(() => {
    const set = new Set([...bwIn.times, ...bwOut.times]);
    return [...set].sort();
  }, [bwIn, bwOut]);
  const inByTime = useMemo(() => new Map(bwIn.times.map((t, k) => [t, bwIn.values[k]])), [bwIn]);
  const outByTime = useMemo(() => new Map(bwOut.times.map((t, k) => [t, bwOut.values[k]])), [bwOut]);

  const bwOption = useMemo<EChartsOption>(
    () => ({
      tooltip: { trigger: 'axis', valueFormatter: (v) => `${Number(v).toFixed(2)} Mbps` },
      legend: { data: ['公网入带宽', '公网出带宽'] },
      grid: { left: 48, right: 16, top: 40, bottom: 24 },
      xAxis: { type: 'category', boundaryGap: false, data: times.map(fmtTime) },
      yAxis: { type: 'value', name: 'Mbps' },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 20 }],
      series: [
        {
          name: '公网入带宽', type: 'line', smooth: true, showSymbol: false,
          data: times.map((t) => Number(((inByTime.get(t) ?? 0) * BPS_TO_MBPS).toFixed(2))),
          lineStyle: { width: 2.5, color: '#2f6df6' },
          areaStyle: { opacity: 0.2, color: '#2f6df6' },
        },
        {
          name: '公网出带宽', type: 'line', smooth: true, showSymbol: false,
          data: times.map((t) => Number(((outByTime.get(t) ?? 0) * BPS_TO_MBPS).toFixed(2))),
          lineStyle: { width: 2.5, color: '#12b76a' },
          areaStyle: { opacity: 0.15, color: '#12b76a' },
        },
      ],
    }),
    [times, inByTime, outByTime],
  );

  // CPU：每实例一条曲线
  const cpuOption = useMemo<EChartsOption>(() => {
    const allTimes = new Set<string>();
    const perInst = selected.map((i) => {
      const m = metricOf(i, 'cpu_total');
      const mp = new Map((m?.points ?? []).map((p) => [p.time, p.value]));
      mp.forEach((_, t) => allTimes.add(t));
      return { name: i.instance_name || i.instance_id, mp };
    });
    const ts = [...allTimes].sort();
    return {
      tooltip: { trigger: 'axis', valueFormatter: (v) => `${Number(v).toFixed(1)} %` },
      legend: { type: 'scroll', data: perInst.map((p) => p.name) },
      grid: { left: 48, right: 16, top: 40, bottom: 24 },
      xAxis: { type: 'category', boundaryGap: false, data: ts.map(fmtTime) },
      yAxis: { type: 'value', name: '%', min: 0, max: 100 },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 20 }],
      series: perInst.map((p) => ({
        name: p.name, type: 'line', smooth: true, showSymbol: false,
        data: ts.map((t) => (p.mp.get(t) ?? 0)),
        lineStyle: { width: 2 },
      })),
    };
  }, [selected]);

  const summary = data?.summary;
  const hasData = instances.length > 0;

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            placeholder="选择阿里云租户"
            style={{ width: 220 }}
            value={tenantId}
            onChange={(v) => { setTenantId(v); setRegionId(undefined); }}
            options={tenants.map((t) => ({ label: `${t.name}（${t.region}）`, value: t.id }))}
          />
          <Select
            placeholder="地域（默认租户地域）"
            allowClear
            style={{ width: 220 }}
            value={regionId}
            onChange={setRegionId}
            options={regions}
            showSearch
            optionFilterProp="label"
          />
          <Select style={{ width: 140 }} value={hours} onChange={setHours} options={HOURS_OPTIONS} />
          <Select
            placeholder="实例（默认全部）"
            mode="multiple"
            allowClear
            maxTagCount="responsive"
            style={{ width: 300 }}
            value={selectedIds}
            onChange={setSelectedIds}
            options={instances.map((i) => ({ label: i.instance_name || i.instance_id, value: i.instance_id }))}
          />
          <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>
            刷新
          </Button>
        </Space>
      </Card>

      {tenants.length === 0 ? (
        <Card>
          <Empty description="还没有阿里云租户，请先到「租户配置」页添加" />
        </Card>
      ) : (
        <Spin spinning={loading}>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col xs={24} sm={6}>
              <Card>
                <Statistic
                  title="当前总公网入带宽"
                  value={((summary?.total_in_bps ?? 0) * BPS_TO_MBPS).toFixed(2)}
                  suffix="Mbps"
                  precision={2}
                  prefix={<ArrowDownOutlined />}
                />
              </Card>
            </Col>
            <Col xs={24} sm={6}>
              <Card>
                <Statistic
                  title="当前总公网出带宽"
                  value={((summary?.total_out_bps ?? 0) * BPS_TO_MBPS).toFixed(2)}
                  suffix="Mbps"
                  precision={2}
                  prefix={<ArrowUpOutlined />}
                />
              </Card>
            </Col>
            <Col xs={24} sm={6}>
              <Card>
                <Statistic title="实例数" value={instances.length} suffix="台" />
              </Card>
            </Col>
            <Col xs={24} sm={6}>
              <Card>
                <Statistic
                  title="数据时间"
                  value={summary?.time ? fmtTime(summary.time) : '-'}
                />
              </Card>
            </Col>
          </Row>

          {!hasData && !loading ? (
            <Card>
              <Empty description="该地域暂无实例（或实例无监控数据）" />
            </Card>
          ) : (
            <>
              <Card title="公网带宽聚合（选中实例求和，CMS 1 分钟粒度）" style={{ marginBottom: 16 }}>
                {times.length === 0 ? (
                  <Empty description="暂无带宽数据" />
                ) : (
                  <Chart option={bwOption} height={380} />
                )}
              </Card>
              <Card title="CPU 使用率（按实例）">
                {selected.length === 0 ? (
                  <Empty description="请先选择实例" />
                ) : (
                  <Chart option={cpuOption} height={340} />
                )}
              </Card>
            </>
          )}
        </Spin>
      )}
    </div>
  );
}
