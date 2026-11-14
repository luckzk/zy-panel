import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Empty,
  Space,
  Spin,
  Tabs,
  Typography,
  Upload,
  message,
} from 'antd';
import { DownloadOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons';
import MfaSettings from '../components/MfaSettings';
import UpdateCenter from '../components/UpdateCenter';
import DailyReportCard from '../components/DailyReportCard';
import {
  downloadBackup,
  getLogs,
  restoreBackup,
  type LogItem,
} from '../api/system';

const { Text } = Typography;

const fmtTime = (iso: string | null) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('zh-CN', { hour12: false });
};

/** 系统设置页：备份恢复 / 安全设置 / 操作日志（全部真实接口） */
export default function System() {
  const navigate = useNavigate();
  const [logs, setLogs] = useState<LogItem[] | null>(null);
  const [logsError, setLogsError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [restoring, setRestoring] = useState(false);

  const loadLogs = async () => {
    try {
      setLogs(await getLogs(100));
      setLogsError(null);
    } catch (e) {
      setLogsError(e instanceof Error ? e.message : '日志加载失败');
    }
  };

  useEffect(() => {
    loadLogs();
    const timer = setInterval(loadLogs, 15000);
    return () => clearInterval(timer);
  }, []);

  const doExport = async () => {
    setExporting(true);
    try {
      await downloadBackup();
      message.success('备份文件已导出');
    } finally {
      setExporting(false);
    }
  };

  return (
    <Tabs
      defaultActiveKey="backup"
      items={[
        {
          key: 'notify',
          label: '通知配置',
          children: (
            <>
              <Card title="消息通知" style={{ maxWidth: 640 }}>
                <Text type="secondary">
                  通知渠道（Telegram / 邮件）的增删改查、启用开关与测试发送，已统一收拢到「通知渠道」页面管理。
                </Text>
                <div style={{ marginTop: 16 }}>
                  <Button type="primary" onClick={() => navigate('/notifications')}>
                    前往通知渠道
                  </Button>
                </div>
              </Card>
              <DailyReportCard />
            </>
          ),
        },
        {
          key: 'backup',
          label: '备份恢复',
          children: (
            <Space direction="vertical" size="large" style={{ width: '100%' }}>
              <Card title="数据备份与恢复" style={{ maxWidth: 640 }}>
                <Space direction="vertical" size="large" style={{ width: '100%' }}>
                  <div>
                    <p style={{ marginBottom: 8, color: '#666' }}>
                      导出加密备份文件（仅管理员），用于迁移或灾难恢复。
                    </p>
                    <Button icon={<DownloadOutlined />} loading={exporting} onClick={doExport}>
                      导出备份
                    </Button>
                  </div>
                  <div>
                    <p style={{ marginBottom: 8, color: '#666' }}>
                      从备份文件恢复租户与任务数据（仅管理员）。
                    </p>
                    <Upload
                      accept=".bin,.bak"
                      beforeUpload={async (file) => {
                        setRestoring(true);
                        try {
                          const r = await restoreBackup(file);
                          const total = Object.values(r.counts ?? {}).reduce((a, b) => a + b, 0);
                          message.success(`备份恢复成功，共 ${total} 条记录`);
                        } finally {
                          setRestoring(false);
                        }
                        return false;
                      }}
                      maxCount={1}
                      showUploadList={false}
                    >
                      <Button icon={<UploadOutlined />} loading={restoring}>
                        上传备份并恢复
                      </Button>
                    </Upload>
                  </div>
                </Space>
              </Card>
              <UpdateCenter />
            </Space>
          ),
        },
        {
          key: 'security',
          label: '安全设置',
          children: <MfaSettings />,
        },
        {
          key: 'logs',
          label: '操作日志',
          children: (
            <Card
              title="操作审计日志"
              extra={
                <Button size="small" icon={<ReloadOutlined />} onClick={loadLogs}>
                  刷新
                </Button>
              }
            >
              {logsError ? (
                <Alert type="error" showIcon message="日志加载失败" description={logsError} />
              ) : logs === null ? (
                <div style={{ textAlign: 'center', padding: 32 }}>
                  <Spin tip="加载中…" />
                </div>
              ) : logs.length ? (
                <div className="log-terminal" style={{ maxHeight: 480, overflowY: 'auto' }}>
                  {logs.map((l) => (
                    <div key={l.id}>
                      [{fmtTime(l.created_at)}] {l.action} {l.detail}
                    </div>
                  ))}
                </div>
              ) : (
                <Empty description="暂无操作记录" />
              )}
              <Text type="secondary" style={{ fontSize: 12 }}>
                每 15 秒自动刷新
              </Text>
            </Card>
          ),
        },
      ]}
    />
  );
}
