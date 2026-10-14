import { useEffect, useState } from 'react';
import { Button, Card, Space, Switch, TimePicker, Typography, message } from 'antd';
import dayjs from 'dayjs';
import {
  getDailyReportConfig,
  sendDailyReportNow,
  updateDailyReportConfig,
} from '../api/system';

const { Text } = Typography;

/** 每日健康报告配置卡：启用开关 + 发送时间 + 立即测试发送 */
export default function DailyReportCard() {
  const [enabled, setEnabled] = useState(false);
  const [time, setTime] = useState('08:00');
  const [lastSent, setLastSent] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [sending, setSending] = useState(false);

  const load = async () => {
    try {
      const cfg = await getDailyReportConfig();
      setEnabled(cfg.enabled);
      setTime(cfg.time || '08:00');
      setLastSent(cfg.last_sent || '');
    } catch {
      /* 拦截器已提示 */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const doSave = async () => {
    setSaving(true);
    try {
      const cfg = await updateDailyReportConfig(enabled, time);
      setEnabled(cfg.enabled);
      setTime(cfg.time);
      message.success('每日报告配置已保存');
    } finally {
      setSaving(false);
    }
  };

  const doSendNow = async () => {
    setSending(true);
    try {
      const r = await sendDailyReportNow();
      if (r.note) message.info(r.note);
      else message.success(`测试发送成功（成功 ${r.channels_ok ?? 0} / 失败 ${r.channels_failed ?? 0}）`);
      load();
    } finally {
      setSending(false);
    }
  };

  return (
    <Card title="每日健康报告" style={{ maxWidth: 640, marginTop: 16 }} loading={loading}>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Text type="secondary">
          每天定时生成实例总览、抢机任务、换 IP 与巡检告警的日报，通过已启用的通知渠道发送。报告数据全部来自实时查询，无数据的章节会自动省略。
        </Text>
        <Space align="center">
          <Text>启用定时发送</Text>
          <Switch checked={enabled} onChange={setEnabled} />
        </Space>
        <Space align="center">
          <Text>发送时间（北京时间）</Text>
          <TimePicker
            format="HH:mm"
            value={dayjs(time, 'HH:mm')}
            onChange={(v) => v && setTime(v.format('HH:mm'))}
            disabled={!enabled}
          />
        </Space>
        {lastSent && <Text type="secondary">上次发送：{lastSent}</Text>}
        <Space>
          <Button type="primary" loading={saving} onClick={doSave}>
            保存配置
          </Button>
          <Button loading={sending} onClick={doSendNow}>
            立即发送测试
          </Button>
        </Space>
        <Text type="secondary" style={{ fontSize: 12 }}>
          测试发送仅走一遍生成与推送流程，不影响定时任务的发送记录。
        </Text>
      </Space>
    </Card>
  );
}
