import { useEffect, useState } from 'react';
import { Card, Col, Empty, Row, Spin, Statistic, Tooltip, Typography } from 'antd';
import { getBillingSummary, type BillingSummary } from '../../api/billing';

const { Text } = Typography;

/** 费用小卡（仅 OCI）：近 90 天费用总额 + 日均 + 服务分布 + 近 30 日迷你柱状 */
export default function BillingCard({ tenantId }: { tenantId: number }) {
  const [data, setData] = useState<BillingSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFailed(false);
    getBillingSummary(tenantId, 90)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setFailed(true); // 错误已由拦截器提示
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  const daily = data?.daily ?? [];
  const last30 = daily.slice(-30);
  const maxDay = last30.reduce((m, d) => Math.max(m, d.amount), 0);

  return (
    <Card title="费用（近 90 天）">
      {loading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin tip="账单接口可能较慢，请稍候…" />
        </div>
      ) : failed || !data ? (
        <Empty description="费用查询失败（账单接口可能超时），不影响其他内容" />
      ) : (
        <>
          <Row gutter={[16, 16]}>
            <Col xs={12} sm={8}>
              <Statistic
                title="费用总额"
                value={data.total}
                precision={2}
                suffix={data.currency || ''}
              />
            </Col>
            <Col xs={12} sm={8}>
              <Statistic title="日均费用" value={data.days > 0 ? data.total / data.days : 0} precision={4} suffix={data.currency || ''} />
            </Col>
            <Col xs={24} sm={8}>
              <Text type="secondary" style={{ fontSize: 13 }}>
                主要服务
              </Text>
              <div style={{ marginTop: 4 }}>
                {data.by_service.length === 0 ? (
                  <Text style={{ fontSize: 13 }}>无费用</Text>
                ) : (
                  data.by_service.slice(0, 3).map((s) => (
                    <div key={s.name} style={{ fontSize: 13, display: 'flex', justifyContent: 'space-between' }}>
                      <Text ellipsis style={{ maxWidth: '60%' }} title={s.name}>
                        {s.name}
                      </Text>
                      <Text>
                        {s.amount.toFixed(2)} {data.currency}
                      </Text>
                    </div>
                  ))
                )}
              </div>
            </Col>
          </Row>
          {last30.length > 0 && maxDay > 0 && (
            <div style={{ marginTop: 16 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                近 30 日每日费用
              </Text>
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 48, marginTop: 6 }}>
                {last30.map((d) => (
                  <Tooltip key={d.date} title={`${d.date}：${d.amount.toFixed(2)} ${data.currency}`}>
                    <div
                      style={{
                        flex: 1,
                        height: `${Math.max(2, Math.round((d.amount / maxDay) * 48))}px`,
                        background: d.amount > 0 ? '#1677ff' : '#e8e8e8',
                        borderRadius: 2,
                        minWidth: 2,
                      }}
                    />
                  </Tooltip>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
