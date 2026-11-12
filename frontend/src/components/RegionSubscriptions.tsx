import { useCallback, useEffect, useState } from 'react';
import { Button, Select, Space, Tag, Typography, message } from 'antd';
import { REGION_CN } from '../types';
import {
  listRegionSubscriptions,
  subscribeRegion,
  type RegionSubscriptionsResult,
} from '../api/tenants';

const { Text } = Typography;

const regionLabel = (regionName: string) =>
  REGION_CN[regionName] ? `${REGION_CN[regionName]} · ${regionName}` : regionName;

/** 区域订阅（仅 OCI）：已订阅列表 + 订阅新区域。租户列表弹窗与租户详情页共用。 */
export default function RegionSubscriptions({ tenantId }: { tenantId: number }) {
  const [data, setData] = useState<RegionSubscriptionsResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [regionToAdd, setRegionToAdd] = useState<string | undefined>(undefined);
  const [subscribing, setSubscribing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await listRegionSubscriptions(tenantId));
    } catch {
      setData(null); // 错误已由拦截器提示
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    load();
  }, [load]);

  const doSubscribe = async () => {
    if (!regionToAdd) return;
    setSubscribing(true);
    try {
      await subscribeRegion(tenantId, regionToAdd);
      message.success('已提交订阅，新区域状态为 IN_PROGRESS，几分钟后变为 READY');
      setRegionToAdd(undefined);
      await load();
    } finally {
      setSubscribing(false);
    }
  };

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <div>
        <Text strong>已订阅（{data?.subscribed.length ?? 0}）</Text>
        <div style={{ marginTop: 8 }}>
          {loading ? (
            <Text type="secondary">加载中…</Text>
          ) : (
            data?.subscribed.map((r) => (
              <div key={r.region_key} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0' }}>
                <Text>{regionLabel(r.region_name)}</Text>
                {r.is_home_region && <Tag color="blue">主区域</Tag>}
                <Tag color={r.status === 'READY' ? 'green' : 'gold'}>{r.status}</Tag>
              </div>
            ))
          )}
        </div>
      </div>
      <div>
        <Text strong>订阅新区域</Text>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <Select
            showSearch
            allowClear
            placeholder="选择区域"
            value={regionToAdd}
            onChange={setRegionToAdd}
            style={{ flex: 1 }}
            loading={loading}
            options={(data?.available ?? []).map((r) => ({
              value: r.region_key,
              label: regionLabel(r.region_name),
            }))}
          />
          <Button type="primary" disabled={!regionToAdd} loading={subscribing} onClick={doSubscribe}>
            订阅
          </Button>
        </div>
        <Text type="secondary" style={{ fontSize: 12 }}>
          默认只能订阅 1 个区域（主区域）；免费号无法订阅其他区域，付费号需先在控制台申请提高区域订阅上限，否则订阅会报错。订阅本身不收费；新区域状态先为 IN_PROGRESS，几分钟后变为 READY 才能使用。
        </Text>
      </div>
    </Space>
  );
}
