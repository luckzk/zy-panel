import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  List,
  Modal,
  Row,
  Skeleton,
  Space,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd';
import {
  CheckCircleOutlined,
  CloudServerOutlined,
  PlusOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  TrophyOutlined,
  UserOutlined,
} from '@ant-design/icons';
import type { EChartsOption } from 'echarts';
import Chart from '../components/Chart';
import CountUp from '../components/CountUp';
import FutCard from '../components/FutCard';
import { REGION_CN } from '../types';
import { useThemeStore } from '../stores/theme';
import { getOverview, type DashboardOverview } from '../api/dashboard';
import { listTenants, type TenantOption } from '../api/tenants';
import { getQuotas, getTraffic, type QuotaItem, type TrafficPoint } from '../api/monitoring';
import { getIpMap, refreshIpMap, type IpMapPoint } from '../api/ipinfo';
import WorldMap from '../components/WorldMap';
import { listSnatchTasks } from '../api/snatch';
import type { SnatchTask } from '../types';
import { api } from '../api/client';

const { Title, Text } = Typography;

/** 统计卡数据（全部来自真实接口） */
interface StatCardData {
  key: string;
  title: string;
  value: string | number;
  unit?: string;
  trend: { value: string; up: boolean };
  spark: number[];
  gradient: string;
  live: boolean;
}

interface LogItem {
  id: number;
  action: string;
  detail: string;
  created_at: string | null;
}

const CARD_ICON: Record<string, React.ReactNode> = {
  instances: <CloudServerOutlined />,
  running: <CheckCircleOutlined />,
  tenants: <UserOutlined />,
  snatch: <ThunderboltOutlined />,
  changeIp: <ReloadOutlined />,
  snatchSuccess: <TrophyOutlined />,
};

const regionName = (code: string) => (REGION_CN[code] ? `${code}（${REGION_CN[code]}）` : code);

const fmtHour = (iso: string) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:00`;
};

const fmtTime = (iso: string | null) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('zh-CN', { hour12: false });
};

const errMsg = (e: unknown, fallback: string) => {
  if (e instanceof Error && e.message) return e.message;
  return fallback;
};

/** 迷你趋势曲线 */
function Sparkline({ data, color }: { data: number[]; color: string }) {
  const option = useMemo<EChartsOption>(
    () => ({
      grid: { left: 0, right: 0, top: 4, bottom: 0 },
      xAxis: { type: 'category', show: false, data: data.map((_, i) => i) },
      yAxis: { type: 'value', show: false },
      series: [
        {
          type: 'line',
          smooth: true,
          showSymbol: false,
          data,
          lineStyle: { width: 2, color },
          areaStyle: { opacity: 0.18, color },
        },
      ],
    }),
    [data, color],
  );
  return <Chart option={option} height={44} />;
}

/** 顶部统计卡 */
function StatCard({ item }: { item: StatCardData }) {
  const futuristic = useThemeStore((s) => s.mode) === 'futuristic';
  return (
    <FutCard
      bodyStyle={{ padding: '16px 16px 8px' }}
    >
      <Space align="start" style={{ width: '100%', justifyContent: 'space-between' }}>
        <div>
          <Text type="secondary" style={{ fontSize: 13 }}>{item.title}</Text>
          <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4, letterSpacing: 0.5 }}>
            {futuristic && typeof item.value === 'number' ? <CountUp value={item.value} /> : item.value}
            {item.unit && <span style={{ fontSize: 14, fontWeight: 400, marginLeft: 4 }}>{item.unit}</span>}
          </div>
        </div>
        <div
          style={{
            width: 44, height: 44, borderRadius: 12, background: item.gradient,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#fff', fontSize: 22,
          }}
        >
          {CARD_ICON[item.key]}
        </div>
      </Space>
      <Tag color="green" style={{ fontSize: 12, marginTop: 2 }}>实时数据</Tag>
      <Sparkline data={item.spark} color="#2f6df6" />
    </FutCard>
  );
}

/** 横向条形图（Region / Shape 分布） */
function BarList({ data, color }: { data: { name: string; value: number }[]; color: string }) {
  const option = useMemo<EChartsOption>(
    () => ({
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: 8, right: 40, top: 8, bottom: 8, containLabel: true },
      xAxis: { type: 'value', show: false },
      yAxis: { type: 'category', data: data.map((d) => d.name), axisLine: { show: false }, axisTick: { show: false } },
      series: [
        {
          type: 'bar',
          data: data.map((d) => d.value),
          barWidth: 14,
          itemStyle: { borderRadius: [0, 7, 7, 0], color },
          label: { show: true, position: 'right', fontWeight: 600 },
        },
      ],
    }),
    [data, color],
  );
  return <Chart option={option} height={240} />;
}

function greeting(): string {
  const h = new Date().getHours();
  if (h < 6) return '夜深了';
  if (h < 12) return '上午好';
  if (h < 14) return '中午好';
  if (h < 18) return '下午好';
  return '晚上好';
}

/** 由真实总览构建 6 张统计卡（spark 用平直线，仅装饰） */
function buildLiveCards(ov: DashboardOverview): StatCardData[] {
  const flat = (v: number) => Array(24).fill(Math.max(v, 0.1));
  const trend = { value: '', up: true };
  return [
    { key: 'instances', title: '实例总数', value: ov.instances.total, live: true, trend, spark: flat(ov.instances.total), gradient: 'linear-gradient(135deg,#2f6df6,#6aa1ff)' },
    { key: 'running', title: '运行中', value: ov.instances.running, live: true, trend, spark: flat(ov.instances.running), gradient: 'linear-gradient(135deg,#12b76a,#5eeaa8)' },
    { key: 'tenants', title: '租户配置', value: ov.tenants, live: true, trend, spark: flat(ov.tenants), gradient: 'linear-gradient(135deg,#7a5af8,#b692f6)' },
    { key: 'snatch', title: '进行中抢机任务', value: ov.snatch.running, live: true, trend, spark: flat(ov.snatch.running), gradient: 'linear-gradient(135deg,#f79009,#fdb022)' },
    { key: 'changeIp', title: '今日换 IP', value: ov.ip_changes_today, live: true, trend, spark: flat(ov.ip_changes_today), gradient: 'linear-gradient(135deg,#0e9fd8,#53c8f5)' },
    { key: 'snatchSuccess', title: '抢机成功', value: ov.snatch.success, live: true, trend, spark: flat(ov.snatch.success), gradient: 'linear-gradient(135deg,#ee46bc,#f9a8d4)' },
  ];
}

const SNATCH_TAG: Record<string, { color: string; text: string }> = {
  success: { color: 'success', text: '已成功' },
  running: { color: 'processing', text: '抢机中' },
  paused: { color: 'default', text: '已暂停' },
  failed: { color: 'error', text: '已失败' },
  pending: { color: 'default', text: '等待中' },
};

/** 总览页：全部数据来自真实接口；无租户时显示引导，无 mock */
export default function Dashboard() {
  const navigate = useNavigate();
  const today = useMemo(
    () => new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' }),
    [],
  );
  const [loading, setLoading] = useState(true);
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [report, setReport] = useState<any>(null);

  const [traffic, setTraffic] = useState<TrafficPoint[] | null>(null);
  const [trafficError, setTrafficError] = useState<string | null>(null);
  const [quotas, setQuotas] = useState<QuotaItem[] | null>(null);
  const [quotasError, setQuotasError] = useState<string | null>(null);
  const [snatchTasks, setSnatchTasks] = useState<SnatchTask[] | null>(null);
  const [logs, setLogs] = useState<LogItem[] | null>(null);
  const [mapPoints, setMapPoints] = useState<IpMapPoint[] | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const [mapRefreshing, setMapRefreshing] = useState(false);

  const runInspection = async () => {
    setInspecting(true);
    try {
      const resp = await api.post('/api/v1/inspection/run', {});
      const data = resp.data;
      setReport(data);
      message.success(`巡检完成：${data.instances_total} 台实例，${data.issues.length} 项异常`);
    } finally {
      setInspecting(false);
    }
  };

  const refreshMap = async () => {
    setMapRefreshing(true);
    setMapError(null);
    try {
      setMapPoints(await refreshIpMap());
      message.success('IP 归属地缓存已刷新');
    } catch (e) {
      setMapError(errMsg(e, '刷新失败'));
    } finally {
      setMapRefreshing(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const ts = await listTenants();
        if (cancelled) return;
        setTenants(ts);
        setLoading(false); // 租户回来就先渲染框架，不等慢数据
        if (!ts.length) return; // 无租户：显示引导，不展示任何假数据
        const firstId = ts[0].id;
        // 全部并行：总览 + 次要数据各自回来各自填，不互相等待
        const settle = async <T,>(p: Promise<T>, ok: (v: T) => void, fail?: (e: unknown) => void) => {
          try {
            const v = await p;
            if (!cancelled) ok(v);
          } catch (e) {
            if (!cancelled && fail) fail(e);
          }
        };
        void settle(getOverview(), (v) => setOverview(v), (e) => setOverviewError(errMsg(e, '总览数据加载失败')));
        void settle(getTraffic(firstId, undefined, 24),
          (v) => setTraffic(v.points), (e) => setTrafficError(errMsg(e, '流量数据加载失败')));
        void settle(getQuotas(firstId),
          (v) => setQuotas(v), (e) => setQuotasError(errMsg(e, '配额数据加载失败')));
        void settle(listSnatchTasks(ts), (v) => setSnatchTasks(v));
        void settle(api.get('/api/v1/system/logs', { params: { limit: 10 } }),
          (v) => setLogs((v.data ?? []) as LogItem[]));
        void settle(getIpMap(),
          (v) => setMapPoints(v), (e) => setMapError(errMsg(e, '实例分布数据加载失败')));
      } catch (e) {
        if (!cancelled) {
          setOverviewError(errMsg(e, '数据加载失败'));
          setLoading(false);
        }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const cards = useMemo(() => (overview ? buildLiveCards(overview) : []), [overview]);
  const regionData = useMemo(
    () => (overview?.instances.by_region ?? []).map((d) => ({ name: regionName(d.name), value: d.value })),
    [overview],
  );
  const shapeData = useMemo(() => overview?.instances.by_shape ?? [], [overview]);

  const bannerSub = useMemo(() => {
    if (!tenants.length) return '还没有配置 OCI 租户，先去添加一个吧';
    if (!overview) return '数据加载中…';
    const parts = [
      overview.snatch.running > 0
        ? `当前有 ${overview.snatch.running} 个抢机任务正在运行`
        : '当前没有运行中的抢机任务',
    ];
    if (overview.errors.length > 0) parts.push(`${overview.errors.length} 个租户查询失败`);
    else parts.push('一切正常');
    return parts.join('，');
  }, [overview, tenants]);

  const trafficOption = useMemo<EChartsOption>(
    () => ({
      tooltip: { trigger: 'axis' },
      legend: { data: ['入站', '出站'] },
      grid: { left: 48, right: 16, top: 40, bottom: 24 },
      xAxis: { type: 'category', boundaryGap: false, data: (traffic ?? []).map((p) => fmtHour(p.time)) },
      yAxis: { type: 'value', name: 'Mbps' },
      series: [
        {
          name: '入站', type: 'line', smooth: true, showSymbol: false,
          data: (traffic ?? []).map((p) => p.inbound_mbps),
          lineStyle: { width: 2.5, color: '#2f6df6' },
          areaStyle: {
            opacity: 0.25,
            color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: '#2f6df6' }, { offset: 1, color: 'rgba(47,109,246,0)' }] },
          },
        },
        {
          name: '出站', type: 'line', smooth: true, showSymbol: false,
          data: (traffic ?? []).map((p) => p.outbound_mbps),
          lineStyle: { width: 2.5, color: '#12b76a' },
          areaStyle: {
            opacity: 0.2,
            color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: '#12b76a' }, { offset: 1, color: 'rgba(18,183,106,0)' }] },
          },
        },
      ],
    }),
    [traffic],
  );

  const statusData = useMemo(() => {
    if (!overview) return [];
    const { total, running, stopped } = overview.instances;
    const other = Math.max(total - running - stopped, 0);
    return [
      { name: '运行中', value: running },
      { name: '已停止', value: stopped },
      { name: '其他状态', value: other },
    ];
  }, [overview]);

  const statusOption = useMemo<EChartsOption>(
    () => ({
      tooltip: { trigger: 'item' },
      legend: { bottom: 0 },
      color: ['#2f6df6', '#f79009', '#12b76a'],
      series: [
        {
          type: 'pie', radius: ['48%', '72%'],
          label: { formatter: '{b}\n{d}%' },
          itemStyle: { borderRadius: 6, borderWidth: 2, borderColor: 'rgba(255,255,255,0.6)' },
          data: statusData,
        },
      ],
    }),
    [statusData],
  );

  return (
    <div>
      {/* 欢迎横幅 */}
      <Card
        style={{
          borderRadius: 16, border: 'none', marginBottom: 16, overflow: 'hidden',
          background: 'linear-gradient(120deg,#0d1b3e 0%,#1b3a8f 55%,#2f6df6 100%)',
        }}
        styles={{ body: { padding: '28px 32px' } }}
      >
        <Row align="middle" justify="space-between">
          <Col>
            <Title level={3} style={{ color: '#fff', margin: 0 }}>
              {greeting()}，欢迎回来 👋
            </Title>
            <Text style={{ color: 'rgba(255,255,255,0.75)', fontSize: 14 }}>
              {today} · {bannerSub}
            </Text>
          </Col>
          <Col>
            <Space>
              <Button size="large" ghost icon={<PlusOutlined />} onClick={() => navigate('/snatch-tasks')}>新建抢机任务</Button>
              <Button
                size="large" type="primary" icon={<ThunderboltOutlined />}
                style={{ background: '#fff', color: '#1b3a8f', border: 'none' }}
                loading={inspecting} onClick={runInspection}
              >
                一键巡检
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      {loading ? (
        <Row gutter={16}>
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Col key={i} xs={12} sm={12} md={8} lg={4}>
              <FutCard bodyStyle={{ padding: 16 }}>
                <Skeleton active paragraph={{ rows: 1 }} title={{ width: '60%' }} />
              </FutCard>
            </Col>
          ))}
        </Row>
      ) : tenants.length === 0 ? (
        <FutCard >
          <Empty
            description="还没有配置 OCI 租户，添加后这里将展示真实数据"
            style={{ padding: '48px 0' }}
          >
            <Button type="primary" size="large" onClick={() => navigate('/tenants')}>去添加租户</Button>
          </Empty>
        </FutCard>
      ) : (
        <>
          {overviewError && (
            <Alert
              type="error" showIcon closable style={{ marginBottom: 16, borderRadius: 12 }}
              message="总览数据加载失败" description={overviewError}
            />
          )}

          {/* 统计卡：数据未到时先展示骨架屏 */}
          <Row gutter={16}>
            {cards.length > 0 ? (
              cards.map((c) => (
                <Col key={c.key} xs={12} sm={12} md={8} lg={4}>
                  <StatCard item={c} />
                </Col>
              ))
            ) : (
              [0, 1, 2, 3, 4, 5].map((i) => (
                <Col key={i} xs={12} sm={12} md={8} lg={4}>
                  <FutCard bodyStyle={{ padding: 16 }}>
                    <Skeleton active paragraph={{ rows: 1 }} title={{ width: '60%' }} />
                  </FutCard>
                </Col>
              ))
            )}
          </Row>

          {/* 流量 + 状态 */}
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col xs={24} lg={16}>
              <FutCard
                title={`实例流量（24 小时${tenants[0] ? ` · ${tenants[0].name}` : ''}）`}
                extra={<Tag color="green">实时数据</Tag>}
                
              >
                {trafficError ? (
                  <Empty description={trafficError} style={{ padding: '40px 0' }} />
                ) : traffic && traffic.length ? (
                  <Chart option={trafficOption} height={320} />
                ) : traffic === null ? (
                  <Skeleton active paragraph={{ rows: 6 }} />
                ) : (
                  <Empty description="暂无流量数据" style={{ padding: '40px 0' }} />
                )}
              </FutCard>
            </Col>
            <Col xs={24} lg={8}>
              <FutCard title="实例状态分布" extra={<Tag color="green">实时数据</Tag>} >
                {statusData.length && statusData.some((d) => d.value > 0) ? (
                  <Chart option={statusOption} height={320} />
                ) : (
                  <Empty description="暂无实例" style={{ padding: '40px 0' }} />
                )}
              </FutCard>
            </Col>
          </Row>

          {/* Region / Shape / 配额 */}
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col xs={24} lg={8}>
              <FutCard title="实例 Region 分布" extra={<Tag color="green">实时数据</Tag>} >
                {regionData.length ? (
                  <BarList data={regionData} color="#2f6df6" />
                ) : (
                  <Empty description="暂无实例" style={{ padding: '40px 0' }} />
                )}
              </FutCard>
            </Col>
            <Col xs={24} lg={8}>
              <FutCard title="实例 Shape 分布" extra={<Tag color="green">实时数据</Tag>} >
                {shapeData.length ? (
                  <BarList data={shapeData} color="#7a5af8" />
                ) : (
                  <Empty description="暂无实例" style={{ padding: '40px 0' }} />
                )}
              </FutCard>
            </Col>
            <Col xs={24} lg={8}>
              <FutCard
                title={`Compute 配额${tenants[0] ? ` · ${tenants[0].name}` : ''}`}
                extra={<Tag color="green">实时数据</Tag>}
                
              >
                {quotasError ? (
                  <Empty description={quotasError} style={{ padding: '40px 0' }} />
                ) : quotas && quotas.length ? (
                  <div style={{ maxHeight: 240, overflowY: 'auto', padding: '8px 4px' }}>
                    {quotas.map((q) => (
                      <Space key={q.name} style={{ width: '100%', justifyContent: 'space-between', marginBottom: 10 }}>
                        <Text style={{ fontSize: 13 }}>{q.name}</Text>
                        <Text strong>{q.value}</Text>
                      </Space>
                    ))}
                  </div>
                ) : quotas === null ? (
                  <Skeleton active paragraph={{ rows: 4 }} />
                ) : (
                  <Empty description="暂无配额数据" style={{ padding: '40px 0' }} />
                )}
              </FutCard>
            </Col>
          </Row>

          {/* 全球实例分布 */}
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={24}>
              <FutCard
                title="全球实例分布"
                extra={
                  <Space>
                    <Tag color="green">实时数据</Tag>
                    <Button
                      type="text" size="small" icon={<ReloadOutlined />}
                      loading={mapRefreshing} onClick={refreshMap}
                    >
                      刷新归属地
                    </Button>
                  </Space>
                }
                
              >
                {mapError ? (
                  <Empty description={mapError} style={{ padding: '40px 0' }} />
                ) : mapPoints && mapPoints.length ? (
                  <WorldMap points={mapPoints} />
                ) : mapPoints === null ? (
                  <Skeleton active paragraph={{ rows: 6 }} />
                ) : (
                  <Empty description="暂无带公网 IP 的实例" style={{ padding: '40px 0' }} />
                )}
              </FutCard>
            </Col>
          </Row>

          {/* 抢机任务 + 最近动态 */}
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col xs={24} lg={12}>
              <FutCard
                title="抢机任务"
                extra={<Space><Tag color="green">实时数据</Tag><a onClick={() => navigate('/snatch-tasks')}>查看全部</a></Space>}
                
              >
                {snatchTasks && snatchTasks.length ? (
                  snatchTasks.slice(0, 5).map((t) => {
                    const tag = SNATCH_TAG[t.status] ?? SNATCH_TAG.pending;
                    return (
                      <div key={t.id} style={{ marginBottom: 16 }}>
                        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                          <Space>
                            <Text strong>{t.name}</Text>
                            <Text type="secondary" style={{ fontSize: 12 }}>{t.shape}</Text>
                          </Space>
                          <Space>
                            <Text type="secondary" style={{ fontSize: 12 }}>{t.attempts} 次尝试</Text>
                            <Tag color={tag.color}>{tag.text}</Tag>
                          </Space>
                        </Space>
                      </div>
                    );
                  })
                ) : snatchTasks === null ? (
                  <Skeleton active paragraph={{ rows: 3 }} />
                ) : (
                  <Empty description="暂无抢机任务" style={{ padding: '24px 0' }} />
                )}
              </FutCard>
            </Col>
            <Col xs={24} lg={12}>
              <FutCard
                title="最近动态"
                extra={<Space><Tag color="green">实时数据</Tag><a onClick={() => navigate('/system')}>操作日志</a></Space>}
                
              >
                {logs && logs.length ? (
                  <Timeline
                    style={{ marginTop: 8 }}
                    items={logs.map((l) => ({
                      color: /fail|error|失败/.test(`${l.action}${l.detail}`) ? 'red' : /success|成功/.test(`${l.action}${l.detail}`) ? 'green' : 'blue',
                      children: (
                        <div>
                          <Text>{l.detail || l.action}</Text>
                          <br />
                          <Text type="secondary" style={{ fontSize: 12 }}>{fmtTime(l.created_at)}</Text>
                        </div>
                      ),
                    }))}
                  />
                ) : logs === null ? (
                  <Skeleton active paragraph={{ rows: 3 }} />
                ) : (
                  <Empty description="暂无操作记录" style={{ padding: '24px 0' }} />
                )}
              </FutCard>
            </Col>
          </Row>
        </>
      )}

      {/* 巡检报告 */}
      <Modal title="巡检报告" open={!!report} onCancel={() => setReport(null)} footer={null} width={640}>
        <p>
          实例总数 {report?.instances_total} · 运行中 {report?.running} · 已停止 {report?.stopped}
          {report?.notified ? <Tag color="green" style={{ marginLeft: 8 }}>已推送通知</Tag> : null}
        </p>
        <List
          dataSource={report?.issues ?? []}
          locale={{ emptyText: '无异常，一切正常' }}
          renderItem={(i: any) => (
            <List.Item>
              <Tag color={i.level === 'error' ? 'red' : i.level === 'warning' ? 'orange' : 'blue'}>{i.level}</Tag>
              <span>{i.tenant} / {i.instance}：{i.message}</span>
            </List.Item>
          )}
        />
        {report?.errors?.length > 0 && (
          <p style={{ color: '#faad14' }}>
            部分租户巡检失败：{report.errors.map((e: any) => e.tenant).join('、')}
          </p>
        )}
      </Modal>
    </div>
  );
}
