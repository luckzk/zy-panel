import { useEffect, useRef, useState } from 'react';
import { Button, Modal, Result, Space, Steps, Typography } from 'antd';
import { CheckCircleOutlined, CloudDownloadOutlined, FileZipOutlined, ReloadOutlined, RocketOutlined } from '@ant-design/icons';
import { applyFrontendUpdate, type FrontendApplyResult } from '../api/system';

const { Text } = Typography;

const STEPS = [
  { title: '下载更新包', icon: <CloudDownloadOutlined /> },
  { title: '校验并解压', icon: <FileZipOutlined /> },
  { title: '替换页面文件', icon: <ReloadOutlined /> },
  { title: '完成', icon: <RocketOutlined /> },
];

interface Props {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}

/** 前端热更进度弹窗：步骤动画 + 成功/失败结果 */
export default function FeUpdateProgress({ open, onClose, onDone }: Props) {
  const [step, setStep] = useState(0);
  const [status, setStatus] = useState<'running' | 'done' | 'error'>('running');
  const [result, setResult] = useState<FrontendApplyResult | null>(null);
  const [errorMsg, setErrorMsg] = useState('');
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!open) return;
    setStep(0);
    setStatus('running');
    setResult(null);
    setErrorMsg('');

    // 步骤动画：请求未返回前缓慢推进到第 3 步等待
    timer.current = setInterval(() => {
      setStep((s) => (s < 2 ? s + 1 : s));
    }, 1200);

    let cancelled = false;
    (async () => {
      try {
        const r = await applyFrontendUpdate();
        if (cancelled) return;
        if (timer.current) clearInterval(timer.current);
        setStep(3);
        // 让"完成"步骤的动画播一下再切结果页
        setTimeout(() => {
          if (cancelled) return;
          setResult(r);
          setStatus('done');
          onDone();
        }, 700);
      } catch (e) {
        if (cancelled) return;
        if (timer.current) clearInterval(timer.current);
        setErrorMsg(e instanceof Error ? e.message : '热更失败');
        setStatus('error');
      }
    })();

    return () => {
      cancelled = true;
      if (timer.current) clearInterval(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open ]);

  return (
    <Modal
      title="前端热更"
      open={open}
      footer={null}
      closable={status !== 'running'}
      maskClosable={status !== 'running'}
      onCancel={onClose}
      destroyOnClose
    >
      {status === 'running' && (
        <div style={{ padding: '16px 0' }}>
          <Steps current={step} items={STEPS.map((s) => ({ title: s.title, icon: s.icon }))} />
          <div style={{ textAlign: 'center', marginTop: 24, color: '#666' }}>
            <Text type="secondary">正在{STEPS[step].title}…请稍候，不要关闭页面</Text>
          </div>
        </div>
      )}
      {status === 'done' && result && (
        <Result
          status="success"
          icon={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
          title="前端已热更"
          subTitle={`已替换 ${result.files} 个文件，刷新浏览器即生效。`}
          extra={
            <Space>
              <Button onClick={onClose}>稍后刷新</Button>
              <Button type="primary" onClick={() => window.location.reload()}>
                立即刷新页面
              </Button>
            </Space>
          }
        />
      )}
      {status === 'error' && (
        <Result
          status="error"
          title="热更失败"
          subTitle={errorMsg}
          extra={<Button onClick={onClose}>关闭</Button>}
        />
      )}
    </Modal>
  );
}
