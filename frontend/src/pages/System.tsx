import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  Modal,
  Space,
  Spin,
  Tabs,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import { DownloadOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons';
import MfaSettings from '../components/MfaSettings';
import FeUpdateProgress from '../components/FeUpdateProgress';
import { FRONTEND_VERSION } from '../version';
import DailyReportCard from '../components/DailyReportCard';
import {
  applyGithubUpdate,
  applyUpdate,
  checkFrontendUpdate,
  checkGithubUpdate,
  checkUpdate,
  downloadBackup,
  getGithubUpdateConfig,
  getLogs,
  getVersion,
  restoreBackup,
  saveGithubUpdateConfig,
  setUpdateFeed,
  type FrontendUpdateCheck,
  type GithubUpdateCheck,
  type LogItem,
  type UpdateCheck,
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
  const [version, setVersion] = useState<string>('');
  const [exporting, setExporting] = useState(false);
  const [restoring, setRestoring] = useState(false);
  // 一键更新
  const [feedUrl, setFeedUrl] = useState('');
  const [updateInfo, setUpdateInfo] = useState<UpdateCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [applying, setApplying] = useState(false);
  // 从 GitHub 更新
  const [ghRepo, setGhRepo] = useState('');
  const [ghBranch, setGhBranch] = useState('main');
  const [ghToken, setGhToken] = useState('');
  const [ghHasToken, setGhHasToken] = useState(false);
  const [ghCheck, setGhCheck] = useState<GithubUpdateCheck | null>(null);
  const [ghChecking, setGhChecking] = useState(false);
  const [ghApplying, setGhApplying] = useState(false);
  // 前端热更新（CI 预构建 dist）
  const [feCheck, setFeCheck] = useState<FrontendUpdateCheck | null>(null);
  const [feChecking, setFeChecking] = useState(false);
  const [feProgressOpen, setFeProgressOpen] = useState(false);
  const [feConfirmOpen, setFeConfirmOpen] = useState(false);
  const [ghConfirmOpen, setGhConfirmOpen] = useState(false);
  const [ghResult, setGhResult] = useState<any>(null);
  const [uploadResult, setUploadResult] = useState<any>(null);

  const loadLogs = async () => {
    try {
      setLogs(await getLogs(100));
      setLogsError(null);
    } catch (e) {
      setLogsError(e instanceof Error ? e.message : '日志加载失败');
    }
  };

  useEffect(() => {
    getVersion().then((v) => setVersion(`${v.name} v${v.version}`)).catch(() => {});
    loadLogs();
    loadGhConfig();
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

  const doCheckUpdate = async () => {
    setChecking(true);
    try {
      const info = await checkUpdate();
      setUpdateInfo(info);
      setFeedUrl(info.feed_url);
      if (info.has_update) message.success(`发现新版本 v${info.latest_version}`);
      else if (info.latest_version) message.info('当前已是最新版本');
    } finally {
      setChecking(false);
    }
  };

  const doSaveFeed = async () => {
    try {
      await setUpdateFeed(feedUrl.trim());
      message.success('更新源已保存');
    } catch { /* 拦截器已提示 */ }
  };

  const loadGhConfig = async () => {
    try {
      const cfg = await getGithubUpdateConfig();
      setGhRepo(cfg.repo);
      setGhBranch(cfg.branch || 'main');
      setGhHasToken(cfg.has_token);
    } catch { /* 拦截器已提示 */ }
  };

  const doSaveGhConfig = async () => {
    try {
      const cfg = await saveGithubUpdateConfig(ghRepo.trim(), ghBranch.trim() || 'main', ghToken.trim());
      setGhRepo(cfg.repo);
      setGhBranch(cfg.branch);
      setGhHasToken(cfg.has_token);
      setGhToken('');
      message.success('GitHub 更新配置已保存');
    } catch { /* 拦截器已提示 */ }
  };

  const doClearGhToken = async () => {
    if (!ghRepo.trim()) {
      message.warning('请先填写仓库地址');
      return;
    }
    try {
      const cfg = await saveGithubUpdateConfig(ghRepo.trim(), ghBranch.trim() || 'main', '', true);
      setGhHasToken(cfg.has_token);
      message.success('Token 已清除');
    } catch { /* 拦截器已提示 */ }
  };

  const doCheckGhUpdate = async () => {
    setGhChecking(true);
    try {
      const info = await checkGithubUpdate();
      setGhCheck(info);
      if (info.has_update) message.success('GitHub 上有新提交');
      else if (info.latest_sha) message.info('已是最新提交');
    } finally {
      setGhChecking(false);
    }
  };

  const doCheckFeUpdate = async () => {
    setFeChecking(true);
    try {
      const info = await checkFrontendUpdate();
      setFeCheck(info);
      if (info.has_update) message.success('前端有新构建');
      else if (!info.notes) message.info('前端已是最新构建');
    } finally {
      setFeChecking(false);
    }
  };

  const doApplyFeUpdate = async () => {
    // 先确认是否有更新（用户可能没点过"检查"）
    let check = feCheck;
    if (!check) {
      try {
        check = await checkFrontendUpdate();
        setFeCheck(check);
      } catch {
        return; // 拦截器已提示错误
      }
    }
    if (!check.has_update && check.asset_updated_at) {
      message.info('前端已是最新构建，无需热更');
      return;
    }
    setFeConfirmOpen(true);
  };

  const doApplyGhUpdate = () => {
    setGhConfirmOpen(true);
  };

  const doConfirmGhUpdate = async () => {
    setGhConfirmOpen(false);
    setGhApplying(true);
    try {
      const r = await applyGithubUpdate();
      setGhResult(r);
      setGhCheck(null);
      loadGhConfig();
    } finally {
      setGhApplying(false);
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
            <Card title="数据备份与恢复" style={{ maxWidth: 640 }}>
              <Space direction="vertical" size="large" style={{ width: '100%' }}>
                {version && (
                  <div>
                    <Text type="secondary">后端版本：</Text>
                    <Tag color="blue">{version}</Tag>
                    <Text type="secondary" style={{ marginLeft: 12 }}>前端版本：</Text>
                    <Tag color="green">zy-panel-frontend v{FRONTEND_VERSION}</Tag>
                  </div>
                )}
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
                    从备份文件恢复租户配置与任务数据（仅管理员）。
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
                <div>
                  <p style={{ marginBottom: 8, color: '#666' }}>
                    检查新版本并一键更新。更新源为 GitHub Releases API 地址（留空则仅支持上传更新包）。
                  </p>
                  <Space direction="vertical" style={{ width: '100%' }} size="middle">
                    <Space style={{ width: '100%' }}>
                      <Input
                        placeholder="https://api.github.com/repos/xxx/zy-panel/releases/latest"
                        value={feedUrl}
                        onChange={(e) => setFeedUrl(e.target.value)}
                        style={{ width: 380 }}
                      />
                      <Button size="small" onClick={doSaveFeed}>保存更新源</Button>
                    </Space>
                    <Space>
                      <Button icon={<ReloadOutlined />} loading={checking} onClick={doCheckUpdate}>
                        检查更新
                      </Button>
                      <Upload
                        accept=".zip"
                        beforeUpload={async (file) => {
                          setApplying(true);
                          try {
                            const r = await applyUpdate(file);
                            setUploadResult(r);
                          } finally {
                            setApplying(false);
                          }
                          return false;
                        }}
                        maxCount={1}
                        showUploadList={false}
                      >
                        <Button icon={<UploadOutlined />} loading={applying}>
                          上传更新包
                        </Button>
                      </Upload>
                    </Space>
                    {updateInfo && (
                      <Alert
                        type={updateInfo.has_update ? 'success' : 'info'}
                        showIcon
                        message={
                          updateInfo.has_update
                            ? `发现新版本 v${updateInfo.latest_version}（当前 v${updateInfo.current_version}）`
                            : updateInfo.latest_version
                              ? `当前已是最新版本 v${updateInfo.current_version}`
                              : `无法检查更新：${updateInfo.notes}`
                        }
                        description={updateInfo.notes || undefined}
                      />
                    )}
                  </Space>
                  <div style={{ borderTop: '1px dashed #d9d9d9', paddingTop: 16 }}>
                    <p style={{ marginBottom: 8, color: '#666' }}>
                      从 GitHub 仓库直接更新：填写仓库地址后，面板会下载指定分支的最新代码并覆盖后端，随后自动重启。公开仓库无需 Token；私有仓库请填写有读取权限的 Token（仅用于下载更新包，加密存储）。
                    </p>
                    <Space direction="vertical" style={{ width: '100%' }} size="middle">
                      <Space style={{ width: '100%' }} wrap={false}>
                        <Input
                          addonBefore="仓库"
                          placeholder="owner/repo（可粘贴仓库 URL）"
                          value={ghRepo}
                          onChange={(e) => setGhRepo(e.target.value)}
                          style={{ width: 300 }}
                        />
                        <Input
                          addonBefore="分支"
                          value={ghBranch}
                          onChange={(e) => setGhBranch(e.target.value)}
                          style={{ width: 150 }}
                        />
                        <Input.Password
                          addonBefore="Token"
                          placeholder={ghHasToken ? '已保存，留空不改' : '私有仓库必填'}
                          value={ghToken}
                          onChange={(e) => setGhToken(e.target.value)}
                          style={{ width: 250 }}
                        />
                        <Button type="primary" size="small" onClick={doSaveGhConfig}>保存配置</Button>
                        {ghHasToken && (
                          <Button size="small" danger onClick={doClearGhToken}>清除 Token</Button>
                        )}
                      </Space>
                      <Space>
                        <Button icon={<ReloadOutlined />} loading={ghChecking} onClick={doCheckGhUpdate}>
                          检查 GitHub 更新
                        </Button>
                        <Button
                          icon={<DownloadOutlined />}
                          loading={ghApplying}
                          disabled={!ghRepo.trim()}
                          onClick={doApplyGhUpdate}
                        >
                          从 GitHub 更新并重启
                        </Button>
                      </Space>
                      {ghCheck && (
                        <Alert
                          type={ghCheck.has_update ? 'success' : ghCheck.latest_sha ? 'info' : 'warning'}
                          showIcon
                          message={
                            ghCheck.latest_sha
                              ? ghCheck.has_update
                                ? `发现新提交 ${ghCheck.latest_sha}（本地 v${ghCheck.current_version}${ghCheck.remote_version ? `，远端 v${ghCheck.remote_version}` : ''}）`
                                : `已是最新提交 ${ghCheck.latest_sha}`
                              : `检查失败：${ghCheck.notes}`
                          }
                          description={
                            ghCheck.latest_sha ? (
                              <div>
                                <div>{ghCheck.latest_message || '（无提交信息）'}</div>
                                <Text type="secondary" style={{ fontSize: 12 }}>
                                  {ghCheck.latest_date ? fmtTime(ghCheck.latest_date) : ''} · {ghCheck.repo}@{ghCheck.branch}
                                  {ghCheck.last_applied_sha ? ` · 上次应用 ${ghCheck.last_applied_sha.slice(0, 12)}` : ''}
                                </Text>
                              </div>
                            ) : undefined
                          }
                        />
                      )}
                    </Space>
                  </div>
                  <div style={{ borderTop: '1px dashed #d9d9d9', paddingTop: 16 }}>
                    <p style={{ marginBottom: 8, color: '#666' }}>
                      前端热更新：GitHub Actions 会在前端代码变更时自动构建静态包并发布到仓库的
                      <Text code>frontend-latest</Text> Release，面板下载后直接替换页面文件，无需重建容器。
                    </p>
                    <Space direction="vertical" style={{ width: '100%' }} size="middle">
                      <Space>
                        <Button icon={<ReloadOutlined />} loading={feChecking} onClick={doCheckFeUpdate}>
                          检查前端更新
                        </Button>
                        <Button icon={<DownloadOutlined />} onClick={doApplyFeUpdate}>
                          热更前端
                        </Button>
                      </Space>
                      <FeUpdateProgress
                        open={feProgressOpen}
                        onClose={() => setFeProgressOpen(false)}
                        onDone={() => setFeCheck(null)}
                      />
                      <Modal
                        title="热更前端？"
                        open={feConfirmOpen}
                        onOk={() => {
                          setFeConfirmOpen(false);
                          setFeProgressOpen(true);
                        }}
                        onCancel={() => setFeConfirmOpen(false)}
                        okText="热更前端"
                        cancelText="取消"
                      >
                        <p>将下载 CI 构建的最新前端静态包并替换当前页面文件，无需重启服务，刷新浏览器即生效。</p>
                      </Modal>
                      <Modal
                        title="从 GitHub 更新并重启？"
                        open={ghConfirmOpen}
                        onOk={doConfirmGhUpdate}
                        onCancel={() => setGhConfirmOpen(false)}
                        okText="更新并重启"
                        okType="danger"
                        cancelText="取消"
                        confirmLoading={ghApplying}
                      >
                        <p>将下载所填分支的最新代码并覆盖后端，3 秒后自动重启服务。前端如有变更需在服务器执行 docker compose up --build -d。</p>
                      </Modal>
                      <Modal
                        title={ghResult ? `已更新至 ${ghResult.github?.sha?.slice(0, 12)}` : '更新结果'}
                        open={ghResult !== null}
                        onOk={() => setGhResult(null)}
                        onCancel={() => setGhResult(null)}
                        cancelText="关闭"
                        width={560}
                      >
                        {ghResult && (
                          <div>
                            <p>提交信息：{ghResult.github?.message || '—'}</p>
                            <p>后端代码：{ghResult.backend_changed ? '已更新' : '无变化'}</p>
                            <p>前端代码：{ghResult.frontend_changed ? '仓库中有变更，可在下方"前端热更新"一键热更' : '无变化'}</p>
                            {ghResult.notes && <p>{ghResult.notes}</p>}
                            <p style={{ color: '#faad14' }}>{ghResult.restart}</p>
                            <Text type="secondary" style={{ fontSize: 12 }}>备份位于：{ghResult.backup_dir}</Text>
                          </div>
                        )}
                      </Modal>
                      <Modal
                        title="更新包已应用"
                        open={uploadResult !== null}
                        onOk={() => setUploadResult(null)}
                        onCancel={() => setUploadResult(null)}
                        cancelText="关闭"
                        width={560}
                      >
                        {uploadResult && (
                          <div>
                            <p>后端代码：{uploadResult.backend_changed ? '已更新' : '无变化'}</p>
                            <p>前端代码：{uploadResult.frontend_changed ? '有变更，需重新构建' : '无变化'}</p>
                            {uploadResult.notes && <p>{uploadResult.notes}</p>}
                            <p style={{ color: '#faad14' }}>{uploadResult.restart}</p>
                            {uploadResult.frontend_changed && (
                              <p style={{ color: '#faad14' }}>
                                前端 dist 在构建时打包，容器内无法热更：请在服务器执行
                                <Text code>docker compose up --build -d</Text> 完成前端更新。
                              </p>
                            )}
                            <Text type="secondary" style={{ fontSize: 12 }}>备份位于：{uploadResult.backup_dir}</Text>
                          </div>
                        )}
                      </Modal>
                      {feCheck && (
                        <Alert
                          type={feCheck.has_update ? 'success' : feCheck.asset_updated_at ? 'info' : 'warning'}
                          showIcon
                          message={
                            feCheck.has_update
                              ? `前端有新构建（${feCheck.asset_updated_at ? fmtTime(feCheck.asset_updated_at) : ''}，${(feCheck.asset_size / 1024).toFixed(0)} KB）`
                              : feCheck.asset_updated_at
                                ? '前端已是最新构建'
                                : `检查失败：${feCheck.notes}`
                          }
                          description={
                            feCheck.asset_updated_at ? (
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                Release: {feCheck.repo}@{feCheck.release_tag}
                                {feCheck.applied_asset_updated_at ? ` · 已应用构建：${fmtTime(feCheck.applied_asset_updated_at)}` : ''}
                              </Text>
                            ) : undefined
                          }
                        />
                      )}
                    </Space>
                  </div>
                </div>
              </Space>
            </Card>
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
