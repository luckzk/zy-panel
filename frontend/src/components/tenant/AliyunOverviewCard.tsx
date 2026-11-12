import { useEffect, useState } from 'react';
import { Card, Col, Empty, Row, Skeleton, Statistic, Typography } from 'antd';
import { getAliyunOverview, type AliyunOverview } from '../../api/aliyun';

const { Text } = Typography;

/** 阿里云租户总览：账户余额 + 当月账单 + 默认地域资源数 */
export default function AliyunOverviewCard({ tenantId }: { tenantId: number }) {
  const [data, setData] = useState<AliyunOverview | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getAliyunOverview(tenantId)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setData(null); // 错误已由拦截器提示
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  const res = data?.resources;
  const bill = data?.bill ?? null;

  return (
    <Card title="账户与费用">
      {loading ? (
        <Skeleton active paragraph={{ rows: 3 }} />
      ) : !data ? (
        <Empty description="总览获取失败，稍后重试" />
      ) : (
        <>
          <Row gutter={[16, 16]}>
            <Col xs={12} sm={8}>
              <Statistic
                title="账户余额"
                value={data.balance ? data.balance.available_amount : '—'}
                suffix={data.balance?.currency ?? ''}
              />
            </Col>
            <Col xs={12} sm={8}>
              <Statistic
                title={`当月账单${bill?.billing_cycle ? `（${bill.billing_cycle}）` : ''}`}
                value={bill ? bill.total : '—'}
                precision={2}
                suffix={bill?.products?.[0]?.currency ?? ''}
              />
            </Col>
            <Col xs={24} sm={8}>
              <Text type="secondary" style={{ fontSize: 13 }}>
                当月主要产品
              </Text>
              <div style={{ marginTop: 4 }}>
                {!bill || bill.products.length === 0 ? (
                  <Text style={{ fontSize: 13 }}>无账单</Text>
                ) : (
                  bill.products.slice(0, 3).map((p) => (
                    <div key={p.product_code + p.product} style={{ fontSize: 13, display: 'flex', justifyContent: 'space-between' }}>
                      <Text ellipsis style={{ maxWidth: '60%' }} title={p.product}>
                        {p.product}
                      </Text>
                      <Text>
                        {p.amount.toFixed(2)} {p.currency}
                      </Text>
                    </div>
                  ))
                )}
              </div>
            </Col>
          </Row>
          <div style={{ marginTop: 20 }}>
            <Text strong style={{ fontSize: 14 }}>
              默认地域资源数（{data.region || '—'}）
            </Text>
            {res ? (
              <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
                <Col xs={12} sm={6}>
                  <Statistic title="ECS 实例" value={res.instances ?? '—'} suffix="台" />
                </Col>
                <Col xs={12} sm={6}>
                  <Statistic title="RDS 实例" value={res.rds ?? '—'} suffix="个" />
                </Col>
                <Col xs={12} sm={6}>
                  <Statistic title="VPC" value={res.vpcs ?? '—'} suffix="个" />
                </Col>
                <Col xs={12} sm={6}>
                  <Statistic title="OSS Bucket" value={res.buckets ?? '—'} suffix="个" />
                </Col>
              </Row>
            ) : (
              <div style={{ marginTop: 8 }}>
                <Text type="secondary">资源数获取失败，稍后重试</Text>
              </div>
            )}
          </div>
        </>
      )}
    </Card>
  );
}
