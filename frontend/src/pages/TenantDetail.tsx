import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeftOutlined } from '@ant-design/icons';
import {
  Button,
  Card,
  Descriptions,
  Empty,
  Modal,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import { REGION_CN } from '../types';
import { getProviderMeta } from '../providers/registry';
import RegionSubscriptions from '../components/RegionSubscriptions';
import {
  detectAccountType,
  getTenant,
  testTenantConnection,
  type TenantDetail,
} from '../api/tenants';

const { Text, Title } = Typography;

/** 租户详情页：基本信息 + 账号检测/连通性操作 + 区域订阅（仅 OCI） */
export default function TenantDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [tenant, setTenant] = useState<TenantDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(false);
  const [detecting, setDetecting] = useState(false);
  const [detectResult, setDetectResult] = useState<{ label: string; reasons: string[] } | null>(null);

  const fetchOne = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      setTenant(await getTenant(Number(id)));
    } catch {
      setTenant(null); // 错误已由拦截器提示
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchOne();
  }, [fetchOne]);

  /** 测试连接：调用真实 OCI/阿里云校验 */
  const testConnection = async () => {
    if (!tenant) return;
    setTesting(true);
    try {
      const result = await testTenantConnection(tenant.id);
      message.success(`「${tenant.name}」连接正常，可用域：${result.availability_domains.join(', ') || '（无）'}`);
      fetchOne();
    } finally {
      setTesting(false);
    }
  };

  /** 自动检测账号类型：启发式判断，结果自动写入 */
  const doDetect = async () => {
    if (!tenant) return;
    setDetecting(true);
    try {
      const r = await detectAccountType(tenant.id);
      const label = r.detected === 'free' ? '免费号' : r.detected === 'paid' ? '付费号' : '未知';
      setDetectResult({ label, reasons: r.reasons });
      fetchOne();
    } finally {
      setDetecting(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    );
  }
  if (!tenant) {
    return <Empty description="租户不存在" style={{ marginTop: 80 }} />;
  }

  const isOci = (tenant.provider || 'oci') === 'oci';
  const meta = getProviderMeta(tenant.provider);
  const regionLabel = REGION_CN[tenant.region]
    ? `${REGION_CN[tenant.region]} · ${tenant.region}`
    : tenant.region;
  const statusTag =
    tenant.test_status === 'success' ? (
      <Tag color="success">正常</Tag>
    ) : tenant.test_status === 'failed' ? (
      <Tag color="error">异常</Tag>
    ) : (
      <Tag color="default">未测试</Tag>
    );
  const accountTag =
    tenant.account_type === 'free' ? (
      <Tag color="green">免费号</Tag>
    ) : tenant.account_type === 'paid' ? (
      <Tag color="gold">付费号</Tag>
    ) : (
      <Text type="secondary">未标记</Text>
    );

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/tenants')}>
          返回租户管理
        </Button>
        <Title level={4} style={{ margin: 0 }}>
          {tenant.name}
        </Title>
        <Tag color={meta.color}>{meta.short}</Tag>
        {accountTag}
        {statusTag}
      </div>

      <Card
        title="基本信息"
        extra={
          <Space>
            <Button size="small" loading={testing} onClick={testConnection}>
              测试连接
            </Button>
            {isOci && (
              <Button size="small" loading={detecting} onClick={doDetect}>
                检测账号类型
              </Button>
            )}
          </Space>
        }
      >
        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label="名称">{tenant.name}</Descriptions.Item>
          <Descriptions.Item label="云厂商">
            <Tag color={meta.color}>{meta.short}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="地域">
            <Tag color="blue">{regionLabel}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="账号类型">{accountTag}</Descriptions.Item>
          <Descriptions.Item label="账号标识">
            {isOci ? (
              <Text copyable>{tenant.tenancy_ocid}</Text>
            ) : (
              <Text copyable>{tenant.access_key_id_masked || '—'}</Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="连通性">
            {tenant.last_tested_at ? (
              <Tooltip
                title={`上次测试：${new Date(tenant.last_tested_at).toLocaleString('zh-CN', { hour12: false })}`}
              >
                {statusTag}
              </Tooltip>
            ) : (
              statusTag
            )}
          </Descriptions.Item>
          {isOci && (
            <>
              <Descriptions.Item label="User OCID">
                <Text copyable>{tenant.user_ocid}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="Fingerprint">{tenant.fingerprint}</Descriptions.Item>
            </>
          )}
          <Descriptions.Item label="代理">{tenant.proxy || '—'}</Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {tenant.created_at
              ? new Date(tenant.created_at).toLocaleString('zh-CN', { hour12: false })
              : '—'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {isOci && (
        <Card title="区域订阅">
          <RegionSubscriptions tenantId={tenant.id} />
        </Card>
      )}

      <Modal
        title={detectResult ? `检测结果：${detectResult.label}` : '检测结果'}
        open={detectResult !== null}
        onOk={() => setDetectResult(null)}
        onCancel={() => setDetectResult(null)}
        cancelText="关闭"
        width={520}
      >
        {detectResult && (
          <div>
            <p style={{ color: '#888' }}>启发式判断，仅供参考。如有误请手动修改。</p>
            <ul style={{ paddingLeft: 20, margin: 0 }}>
              {detectResult.reasons.map((x, i) => (
                <li key={i} style={{ fontSize: 13 }}>
                  {x}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Modal>
    </Space>
  );
}
