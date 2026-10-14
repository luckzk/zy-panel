import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Col, Empty, Progress, Row, Select, Space, Spin, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { listTenants, type TenantOption } from '../api/tenants';
import { getFreeTierSummary, type FreeTierSummary } from '../api/free_tier';

const { Text } = Typography;

function percent(used: number | null, limit: number | null): number {
  if (used == null || limit == null || limit <= 0) return 0;
  return Math.min(100, Math.round((used / limit) * 100));
}

function statusOf(used: number | null, limit: number | null): 'success' | 'exception' | 'normal' {
  if (used == null || limit == null) return 'normal';
  const p = used / limit;
  if (p >= 1) return 'exception';
  if (p >= 0.8) return 'exception';
  return 'success';
}

/** 免费额度：Always Free 资源使用情况（只读汇总） */
export default function FreeTier() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number>();
  const [data, setData] = useState<FreeTierSummary | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    listTenants().then((ts) => {
      setTenants(ts);
      if (ts.length > 0) setTenantId(ts[0].id);
    }).catch(() => {});
  }, []);

  const fetch = useCallback(async (refresh = false) => {
    if (!tenantId) return;
    setLoading(true);
    try {
      setData(await getFreeTierSummary(tenantId, refresh));
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    setData(null);
    fetch(false);
  }, [tenantId, fetch]);

  return (
    <Card
      title="免费额度使用情况"
      extra={
        <Space>
          <Select
            style={{ width: 220 }}
            placeholder="选择租户"
            value={tenantId}
            onChange={setTenantId}
            options={tenants.map((t) => ({ value: t.id, label: `${t.name}（${t.region}）` }))}
          />
          <Button icon={<ReloadOutlined />} onClick={() => fetch(true)} loading={loading}>
            刷新
          </Button>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="Always Free 额度对照"
        description="按 Oracle 官方 Always Free 标准统计（2 台 AMD Micro / 4C24G ARM / 200GB 块存储 / 20GB 对象存储 / 2 个自治数据库 / 10TB 月出站流量 / 历史免费上限 1 个负载均衡器）。VCN、保留公网 IP、DNS Zone、文件系统仅统计数量（本身免费或无明确免费上限）。数据来自各服务实时查询，后端缓存 10 分钟；出站流量按实例 VNIC 监控累加估算，仅供参考。"
      />
      {loading && !data ? (
        <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>
      ) : !data || data.items.length === 0 ? (
        <Empty description="暂无数据，请先选择租户" />
      ) : (
        <>
          <Text type="secondary" style={{ fontSize: 12 }}>
            统计时间：{new Date(data.generated_at).toLocaleString('zh-CN', { hour12: false })}
            {data.cached ? '（缓存）' : ''}
          </Text>
          <Row gutter={[16, 16]} style={{ marginTop: 12 }}>
            {data.items.map((it) => (
              <Col xs={24} sm={12} lg={8} key={it.key}>
                <Card size="small" title={it.name}>
                  {it.unknown ? (
                    <Text type="secondary">查询失败，稍后重试</Text>
                  ) : (
                    <>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                        <Text strong style={{ fontSize: 20 }}>
                          {it.used}
                          <Text type="secondary" style={{ fontSize: 13 }}>
                            {it.limit != null ? ` / ${it.limit} ${it.unit}` : ` ${it.unit}（仅统计）`}
                          </Text>
                        </Text>
                        {it.limit != null && (
                          <Text type={percent(it.used, it.limit) >= 80 ? 'danger' : 'secondary'}>
                            {percent(it.used, it.limit)}%
                          </Text>
                        )}
                      </div>
                      {it.limit != null && (
                        <Progress
                          percent={percent(it.used, it.limit)}
                          status={statusOf(it.used, it.limit)}
                          showInfo={false}
                        />
                      )}
                      {it.key === 'arm_ocpus' && Array.isArray((it as { detail?: unknown }).detail) && (
                        <div style={{ marginTop: 8 }}>
                          {((it as { detail: Array<{ name: string; ocpus: number; memory_in_gbs: number }> }).detail).map((d, i) => (
                            <Text key={i} type="secondary" style={{ fontSize: 12, display: 'block' }}>
                              {d.name}：{d.ocpus} OCPU / {d.memory_in_gbs} GB
                            </Text>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </Card>
              </Col>
            ))}
          </Row>
        </>
      )}
    </Card>
  );
}
