import { useEffect, useState } from 'react';
import { Card, Empty, List, Spin, Typography } from 'antd';
import { getTenantRecentOperations, type RecentOperation } from '../../api/tenants';

const { Text } = Typography;

/** 最近操作记录：面板审计日志里提到该租户名的条目（文本匹配，仅供参考） */
export default function RecentOperations({ tenantId }: { tenantId: number }) {
  const [items, setItems] = useState<RecentOperation[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getTenantRecentOperations(tenantId, 10)
      .then((list) => {
        if (!cancelled) setItems(list);
      })
      .catch(() => {
        if (!cancelled) setItems([]); // 错误已由拦截器提示
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  return (
    <Card
      title="最近操作记录"
      extra={
        <Text type="secondary" style={{ fontSize: 12 }}>
          按租户名匹配审计日志，仅供参考
        </Text>
      }
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin />
        </div>
      ) : items.length === 0 ? (
        <Empty description="暂无与该租户相关的操作记录" />
      ) : (
        <List
          size="small"
          dataSource={items}
          renderItem={(it) => (
            <List.Item>
              <List.Item.Meta
                title={
                  <span style={{ fontSize: 13 }}>
                    <Text strong>{it.action}</Text>
                    {it.detail ? <Text type="secondary">　{it.detail}</Text> : null}
                  </span>
                }
                description={
                  <span style={{ fontSize: 12 }}>
                    {it.created_at
                      ? new Date(it.created_at).toLocaleString('zh-CN', { hour12: false })
                      : '—'}
                    {it.username ? ` · ${it.username}` : ''}
                  </span>
                }
              />
            </List.Item>
          )}
        />
      )}
    </Card>
  );
}
