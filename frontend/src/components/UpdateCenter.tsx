import { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Modal,
  Space,
  Steps,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import { DownloadOutlined, GithubOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons';
import { FRONTEND_VERSION } from '../version';
import {
  applyAllUpdate,
  applyUpdate,
  checkAllUpdate,
  getVersion,
  type AllUpdateApplyResult,
  type AllUpdateCheck,
  type UpdateApplyResult,
} from '../api/system';

const { Text } = Typography;

const fmtTime = (iso: string | null) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('zh-CN', { hour12: false });
};

/** 等后端重启恢复：每 2 秒调一次版本接口，最多 60 秒 */
async function waitForBackend(): Promise<boolean> {
  for (let i = 0; i < 30; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    try {
      await getVersion();
      return true;
    } catch {
      /* 还没起来 */
    }
  }
  return false;
}

/**
 * 系统更新中心：前后端一次检查、一键更新。
 * 更新源固定为 luckzk/zy-panel@main（后端写死），先热更前端再更新后端并重启。
 */
export default function UpdateCenter() {
  const [version, setVersion] = useState('');
  const [checking, setChecking] = useState(false);
  const [check, setCheck] = useState<AllUpdateCheck | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [applying, setApplying] = useState(false);
  const [progressOpen, setProgressOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [stepError, setStepError] = useState('');
  const [applyResult, setApplyResult] = useState<AllUpdateApplyResult | null>(null);
  const [backendBack, setBackendBack] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<UpdateApplyResult | null>(null);

  useEffect(() => {
    getVersion()
      .then((v) => setVersion(`${v.name} v${v.version}`))
      .catch(() => {});
  }, []);

  const beHas = !!check?.backend.has_update;
  const feHas = !!check?.frontend.has_update;

  const doCheck = async () => {
    setChecking(true);
    try {
      const info = await checkAllUpdate();
      setCheck(info);
      if (!info.backend.has_update && !info.frontend.has_update) {
        message.success('前后端均已是最新');
        return;
      }
      setConfirmOpen(true);
    } finally {
      setChecking(false);
    }
  };

  /** 执行一键更新；flags 决定更新哪一侧（重试后端时只传后端） */
  const runApply = async (updateBackend: boolean, updateFrontend: boolean) => {
    setConfirmOpen(false);
    setApplying(true);
    setProgressOpen(true);
    setStep(0);
    setStepError('');
    setApplyResult(null);
    setBackendBack(false);
    try {
      const r = await applyAllUpdate(updateBackend, updateFrontend);
      setApplyResult(r);
      setStep(1);
      if (r.backend_error) {
        setStepError(`后端更新失败：${r.backend_error}（前端已更新，可重试后端更新）`);
        setStep(3);
        return;
      }
      if (r.backend) {
        setStep(2);
        const back = await waitForBackend();
        setBackendBack(back);
        if (!back) setStepError('后端 60 秒内未恢复，请手动刷新页面或检查容器日志');
      }
      setStep(3);
    } catch (e) {
      setStepError(e instanceof Error ? e.message : '更新失败');
      setStep(3);
    } finally {
      setApplying(false);
    }
  };

  return (
    <Card title="系统更新" style={{ maxWidth: 640 }}>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <div>
          <Text type="secondary">后端版本：</Text>
          <Tag color="blue">{version || '—'}</Tag>
          <Text type="secondary" style={{ marginLeft: 12 }}>前端版本：</Text>
          <Tag color="green">zy-panel-frontend v{FRONTEND_VERSION}</Tag>
        </div>
        <div>
          <GithubOutlined style={{ marginRight: 6 }} />
          <Text type="secondary">更新源：luckzk/zy-panel @ main（已固定）</Text>
        </div>
        <Space>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            loading={checking || applying}
            onClick={doCheck}
          >
            一键更新
          </Button>
          <Upload
            accept=".zip"
            beforeUpload={async (file) => {
              setUploading(true);
              try {
                const r = await applyUpdate(file);
                setUploadResult(r);
              } finally {
                setUploading(false);
              }
              return false;
            }}
            maxCount={1}
            showUploadList={false}
          >
            <Button icon={<UploadOutlined />} loading={uploading}>
              上传更新包
            </Button>
          </Upload>
        </Space>
        <Text type="secondary" style={{ fontSize: 12 }}>
          一键更新先热更前端（刷新即生效），再从 GitHub 更新后端并自动重启；上传更新包为离线备用方式。
        </Text>
        {check && (beHas || feHas) && (
          <Alert
            type="success"
            showIcon
            message={
              [
                beHas ? `后端有新提交 ${check.backend.latest_sha}` : '后端已是最新',
                feHas ? '前端有新构建' : '前端已是最新',
              ].join('；')
            }
          />
        )}
        {uploadResult && (
          <Alert
            type="info"
            showIcon
            message="更新包已应用"
            description={
              <div>
                <div>后端代码：{uploadResult.backend_changed ? '已更新' : '无变化'}</div>
                <div>前端代码：{uploadResult.frontend_changed ? '有变更，需重新构建' : '无变化'}</div>
                {uploadResult.restart && <div style={{ color: '#faad14' }}>{uploadResult.restart}</div>}
                <Text type="secondary" style={{ fontSize: 12 }}>备份位于：{uploadResult.backup_dir}</Text>
              </div>
            }
          />
        )}
      </Space>

      <Modal
        title="一键更新前后端？"
        open={confirmOpen}
        onOk={() => runApply(beHas, feHas)}
        onCancel={() => setConfirmOpen(false)}
        okText="开始更新"
        cancelText="取消"
      >
        {check && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <div>
              <b>后端：</b>
              {beHas ? (
                <span>
                  发现新提交 {check.backend.latest_sha}
                  （本地 v{check.backend.current_version}
                  {check.backend.remote_version ? `，远端 v${check.backend.remote_version}` : ''}）
                  <br />
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {check.backend.latest_message || '（无提交信息）'}
                    {check.backend.latest_date ? ` · ${fmtTime(check.backend.latest_date)}` : ''}
                  </Text>
                </span>
              ) : (
                '已是最新，无需更新'
              )}
            </div>
            <div>
              <b>前端：</b>
              {feHas ? (
                <span>
                  有新构建
                  {check.frontend.asset_updated_at ? `（${fmtTime(check.frontend.asset_updated_at)}，${(check.frontend.asset_size / 1024).toFixed(0)} KB）` : ''}
                </span>
              ) : (
                '已是最新，无需更新'
              )}
            </div>
            <Text type="secondary" style={{ fontSize: 12 }}>
              先热更前端，再更新后端并在 3 秒后自动重启；更新完成前请不要关闭页面。
            </Text>
          </Space>
        )}
      </Modal>

      <Modal
        title="正在更新"
        open={progressOpen}
        footer={
          step === 3
            ? [
                applyResult?.backend_error ? (
                  <Button key="retry" loading={applying} onClick={() => runApply(true, false)}>
                    重试后端更新
                  </Button>
                ) : null,
                <Button key="refresh" type="primary" icon={<ReloadOutlined />} onClick={() => window.location.reload()}>
                  刷新页面
                </Button>,
              ]
            : null
        }
        onCancel={() => {
          if (step === 3) setProgressOpen(false);
        }}
        closable={step === 3}
        maskClosable={false}
        width={560}
      >
        <Steps
          current={step}
          status={stepError ? 'error' : 'process'}
          direction="vertical"
          size="small"
          items={[
            { title: '前端热更', description: applyResult?.frontend ? `已替换 ${applyResult.frontend.files} 个文件` : '等待中' },
            { title: '后端更新', description: applyResult?.backend ? `已更新至 ${applyResult.backend.github?.sha?.slice(0, 12) || ''}` : applyResult?.backend_error ? '失败' : '等待中' },
            { title: '等待后端重启', description: backendBack ? '后端已恢复' : '后端重启中…' },
            { title: '完成', description: step === 3 ? '可以刷新页面查看新版本' : '等待中' },
          ]}
        />
        {stepError && (
          <Alert type="error" showIcon style={{ marginTop: 16 }} message={stepError} />
        )}
        {applyResult?.restart && step === 3 && !stepError && (
          <Alert type="success" showIcon style={{ marginTop: 16 }} message={applyResult.restart} />
        )}
      </Modal>
    </Card>
  );
}
