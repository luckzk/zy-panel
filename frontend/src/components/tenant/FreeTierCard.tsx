import { useCallback, useEffect, useState } from 'react';
import { ReloadOutlined } from '@ant-design/icons';
import { Button, Card, Col, Empty, Progress, Row, Spin, Typography } from 'antd';
import { getFreeTierSummary, type FreeTierSummary } from '../../api/free_tier';

const { Text } = Typography;

function percent(used: number | null, limit: number | null): number {
  if (used === null || limit === null || limit === 0) return 0;
  return Math.min(100, Math.round((used / limit) * 100));
}

function statusOf(used: number | null, limit: number | null): 'success' | 'normal' | 'exception' {
  const p = percent(used, limit);
  if (p >= 100) return 'exception';
  if (p >= 80) return 'normal';
  return 'success';
}

/** 免费额度使用情况（仅 OCI）：复用免费额度页的接口与渲染 */
export default function FreeTierCard({ tenantId }: { tenantId: number }) {
  const [data, setData] = useState<FreeTierSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const fetch = useCallback(
    async (refresh = false) => {
      setLoading(true);
      try {
        setData(await getFreeTierSummary(tenantId, refresh));
      } catch {
        setData(null); // 错误已由拦截器提示
      } finally {
        setLoading(false);
      }
    },
    [tenantId],
  );

  useEffect(() => {
    fetch();
  }, [fetch]);

  return (
    <Card
      title="免费额度使用情况"
      extra={
        <Button size="small" icon={<ReloadOutlined />} onClick={() => fetch(true)} loading={loading}>
          刷新
        </Button>
      }
    >
      {loading && !data ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin />
        </div>
      ) : !data || data.items.length === 0 ? (
        <Empty description="暂无数据" />
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
                        <Progress percent={percent(it.used, it.limit)} status={statusOf(it.used, it.limit)} showInfo={false} />
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
