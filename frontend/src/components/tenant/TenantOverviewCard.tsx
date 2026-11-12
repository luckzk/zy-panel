import { Link } from 'react-router-dom';
import { Card, Col, Descriptions, Empty, Row, Skeleton, Statistic, Tag, Typography } from 'antd';
import type { TenantOverview } from '../../api/tenants';

const { Text } = Typography;

/** OCI 资源概览 + 配额快照 + 可用域/Compartment + IAM 摘要（总览数据由详情页传入） */
export default function TenantOverviewCard({
  overview,
  loading,
}: {
  overview: TenantOverview | null;
  loading: boolean;
}) {
  const r = overview?.resources ?? null;
  const q = overview?.quotas ?? null;
  const iam = overview?.iam ?? null;
  const ads = overview?.availability_domains ?? null;
  const comps = overview?.compartments ?? null;

  const quotaRows: { label: string; value: number | null; unit: string }[] = q
    ? [
        { label: 'Micro 实例上限', value: q.micro_limit, unit: '台' },
        { label: 'A1 核数配额', value: q.a1_core_limit, unit: '核' },
        { label: 'E2 core-count', value: q.e2_core_limit, unit: '' },
        { label: 'E3 core-count', value: q.e3_core_limit, unit: '' },
        { label: 'E4 core-count', value: q.e4_core_limit, unit: '' },
        { label: 'E5 core-count', value: q.e5_core_limit, unit: '' },
        { label: 'E6 core-count', value: q.e6_core_limit, unit: '' },
        { label: '区域订阅上限', value: q.subscribed_region_limit, unit: '个' },
      ]
    : [];

  return (
    <Card title="资源概览">
      {loading ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : !overview ? (
        <Empty description="总览获取失败，稍后重试" />
      ) : (
        <>
          {r ? (
            <Row gutter={[16, 16]}>
              <Col xs={12} sm={8} lg={6}>
                <Statistic title="实例（运行中）" value={r.instances_total} suffix="台" />
              </Col>
              <Col xs={12} sm={8} lg={6}>
                <Statistic title="AMD Micro" value={r.micro_count} suffix="台" />
              </Col>
              <Col xs={12} sm={8} lg={6}>
                <Statistic title="ARM 算力" value={r.a1_ocpu} suffix="OCPU" />
              </Col>
              <Col xs={12} sm={8} lg={6}>
                <Statistic title="ARM 内存" value={r.a1_memory_gb} suffix="GB" />
              </Col>
              <Col xs={12} sm={8} lg={6}>
                <Statistic title="块存储总量" value={r.block_storage_gb} suffix="GB" />
              </Col>
              <Col xs={12} sm={8} lg={6}>
                <Statistic title="自治数据库" value={r.adb_count} suffix="个" />
              </Col>
              <Col xs={12} sm={8} lg={6}>
                <Statistic title="VCN" value={r.vcn_count} suffix="个" />
              </Col>
              <Col xs={12} sm={8} lg={6}>
                <Statistic
                  title={
                    <span>
                      IAM 用户 / 用户组{' '}
                      <Link to="/iam" style={{ fontSize: 12 }}>
                        查看
                      </Link>
                    </span>
                  }
                  value={iam ? `${iam.users} / ${iam.groups}` : '—'}
                />
              </Col>
              <Col xs={24}>
                <Text type="secondary" style={{ fontSize: 13 }}>
                  付费机型实例：
                </Text>{' '}
                {r.paid_shapes.length === 0 ? (
                  <Text style={{ fontSize: 13 }}>无（仅免费机型）</Text>
                ) : (
                  r.paid_shapes.map((s) => (
                    <Tag key={s} color="gold" style={{ marginBottom: 4 }}>
                      {s}
                    </Tag>
                  ))
                )}
              </Col>
              <Col xs={24}>
                <Text type="secondary" style={{ fontSize: 13 }}>
                  可用域：
                </Text>{' '}
                {ads === null ? (
                  <Text style={{ fontSize: 13 }}>获取失败</Text>
                ) : ads.length === 0 ? (
                  <Text style={{ fontSize: 13 }}>—</Text>
                ) : (
                  ads.map((a) => (
                    <Tag key={a} color="blue" style={{ marginBottom: 4 }}>
                      {a}
                    </Tag>
                  ))
                )}
              </Col>
              <Col xs={24}>
                <Text type="secondary" style={{ fontSize: 13 }}>
                  Compartment：
                </Text>{' '}
                {comps === null ? (
                  <Text style={{ fontSize: 13 }}>获取失败</Text>
                ) : comps.length === 0 ? (
                  <Text style={{ fontSize: 13 }}>—</Text>
                ) : (
                  <>
                    {comps.slice(0, 6).map((c) => (
                      <Tag key={c.id} style={{ marginBottom: 4 }}>
                        {c.name}
                      </Tag>
                    ))}
                    {comps.length > 6 && <Text type="secondary">等 {comps.length} 个</Text>}
                  </>
                )}
              </Col>
            </Row>
          ) : (
            <Text type="secondary">资源统计获取失败，稍后重试</Text>
          )}

          <div style={{ marginTop: 20 }}>
            <Text strong style={{ fontSize: 14 }}>
              配额快照
            </Text>
            <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
              Limits API 实时值；免费号 E2–E6 配额为 0
            </Text>
            {q ? (
              <Descriptions column={4} size="small" bordered style={{ marginTop: 8 }}>
                {quotaRows.map((row) => (
                  <Descriptions.Item key={row.label} label={row.label}>
                    {row.value === null ? '—' : `${row.value}${row.unit ? ` ${row.unit}` : ''}`}
                  </Descriptions.Item>
                ))}
              </Descriptions>
            ) : (
              <div style={{ marginTop: 8 }}>
                <Text type="secondary">配额获取失败，稍后重试</Text>
              </div>
            )}
          </div>
        </>
      )}
    </Card>
  );
}
