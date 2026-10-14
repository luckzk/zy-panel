import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Form, Input, Modal, Space, Spin, Typography, message } from 'antd';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import {
  createConsoleConnection,
  deleteConsoleConnection,
  getResetPasswordTask,
  listConsoleConnections,
  startResetPassword,
  type ConsoleConnection,
  type ResetPasswordTask,
} from '../api/console';

const { Text } = Typography;

function getToken(): string {
  return localStorage.getItem('oci_panel_token') || '';
}

type Phase = 'idle' | 'creating' | 'ready' | 'connecting' | 'connected' | 'failed';

interface Props {
  tenantId: number;
  instanceId: string;
  instanceName: string;
}

/** 串行控制台：OCI Console Connection，实例 SSH 挂掉时也能进串口救砖 */
export default function SerialConsole({ tenantId, instanceId, instanceName }: Props) {
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>('idle');
  const [conn, setConn] = useState<ConsoleConnection | null>(null);
  const [error, setError] = useState('');
  // 自动重置密码
  const [resetOpen, setResetOpen] = useState(false);
  const [resetTask, setResetTask] = useState<ResetPasswordTask | null>(null);
  const [resetForm] = Form.useForm();
  const resetPoll = useRef<number | null>(null);
  const logBoxRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<HTMLDivElement>(null);
  const term = useRef<Terminal | null>(null);
  const ws = useRef<WebSocket | null>(null);
  const pollTimer = useRef<number | null>(null);

  const disposeTerminal = () => {
    try { ws.current?.close(); } catch { /* ignore */ }
    ws.current = null;
    term.current?.dispose();
    term.current = null;
  };

  const stopPoll = () => {
    if (pollTimer.current) {
      window.clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  };

  useEffect(() => () => { disposeTerminal(); stopPoll(); stopResetPoll(); }, []);

  /** 打开终端并连 WebSocket */
  const openTerminal = (connectionId: number) => {
    disposeTerminal();
    setPhase('connecting');
    const t = new Terminal({
      cursorBlink: true,
      fontSize: 14,
      fontFamily: 'Menlo, Consolas, monospace',
      theme: { background: '#0d1117' },
    });
    term.current = t;
    // 等 Modal 内容渲染后再 open
    setTimeout(() => {
      if (!termRef.current) return;
      t.open(termRef.current);
      t.writeln('正在接入实例串口…');
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const url = `${proto}://${window.location.host}/ws/console?token=${encodeURIComponent(getToken())}&connection_id=${connectionId}`;
      const socket = new WebSocket(url);
      ws.current = socket;
      socket.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === 'output') {
            t.write(msg.data);
            setPhase((p) => (p === 'connecting' ? 'connected' : p));
          } else if (msg.type === 'error') {
            t.writeln(`\r\n❌ ${msg.message}`);
            message.error(msg.message);
            setPhase('failed');
            setError(msg.message);
          } else if (msg.type === 'closed') {
            t.writeln('\r\n连接已关闭');
            setPhase('ready');
          }
        } catch { /* ignore */ }
      };
      socket.onerror = () => {
        t.writeln('\r\n❌ WebSocket 连接失败');
        setPhase('failed');
        setError('WebSocket 连接失败');
      };
      socket.onclose = () => setPhase((p) => (p === 'connected' ? 'ready' : p));
      t.onData((data) => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'input', data }));
        }
      });
    }, 60);
  };

  /** 轮询直到 ACTIVE */
  const pollUntilActive = (connectionId: number) => {
    stopPoll();
    const started = Date.now();
    pollTimer.current = window.setInterval(async () => {
      if (Date.now() - started > 200_000) {
        stopPoll();
        setPhase('failed');
        setError('等待控制台连接就绪超时（200s），请稍后重试或删除重建');
        return;
      }
      try {
        const items = await listConsoleConnections(tenantId, instanceId);
        const hit = items.find((c) => c.id === connectionId);
        if (!hit) return;
        setConn(hit);
        if (hit.state === 'ACTIVE') {
          stopPoll();
          setPhase('ready');
          openTerminal(hit.id);
        } else if (hit.state === 'FAILED') {
          stopPoll();
          setPhase('failed');
          setError(hit.error || '控制台连接创建失败');
        }
      } catch { /* 轮询错误忽略，继续 */ }
    }, 4000);
  };

  const start = async () => {
    setOpen(true);
    setPhase('creating');
    setError('');
    setConn(null);
    try {
      // 先复用已存在的 ACTIVE 连接
      const items = await listConsoleConnections(tenantId, instanceId);
      const active = items.find((c) => c.state === 'ACTIVE');
      if (active) {
        setConn(active);
        setPhase('ready');
        openTerminal(active.id);
        return;
      }
      const created = await createConsoleConnection(tenantId, instanceId, instanceName);
      setConn(created);
      if (created.state === 'ACTIVE') {
        setPhase('ready');
        openTerminal(created.id);
      } else {
        pollUntilActive(created.id);
      }
    } catch {
      setPhase('failed');
      setError('创建控制台连接失败');
    }
  };

  const handleDelete = async () => {
    if (!conn) return;
    try {
      await deleteConsoleConnection(tenantId, conn.id);
      message.success('控制台连接已删除');
    } catch { /* 错误已由拦截器提示 */ }
    disposeTerminal();
    stopPoll();
    setOpen(false);
    setPhase('idle');
    setConn(null);
  };

  const handleClose = () => {
    disposeTerminal();
    stopPoll();
    stopResetPoll();
    setOpen(false);
    setPhase('idle');
    setResetTask(null);
  };

  /** ---- 自动重置系统密码 ---- */
  const stopResetPoll = () => {
    if (resetPoll.current) {
      window.clearInterval(resetPoll.current);
      resetPoll.current = null;
    }
  };

  const pollResetTask = (taskId: string) => {
    stopResetPoll();
    resetPoll.current = window.setInterval(async () => {
      try {
        const t = await getResetPasswordTask(taskId);
        setResetTask(t);
        // 日志自动滚到底
        setTimeout(() => {
          logBoxRef.current?.scrollTo({ top: logBoxRef.current.scrollHeight });
        }, 50);
        if (t.state !== 'running') {
          stopResetPoll();
          if (t.state === 'success') message.success('系统密码重置成功');
          else message.error(t.error || '密码重置失败');
        }
      } catch { /* 忽略单次轮询错误 */ }
    }, 3000);
  };

  const submitReset = async () => {
    try {
      const v = await resetForm.validateFields();
      if (v.new_password !== v.confirm) {
        message.error('两次输入的密码不一致');
        return;
      }
      setResetOpen(false);
      setResetTask({
        task_id: '', state: 'running', step: '提交中…', logs: [], error: '',
        created_at: '',
      });
      try {
        const taskId = await startResetPassword(
          tenantId, instanceId, instanceName, v.username.trim(), v.new_password,
        );
        resetForm.resetFields();
        pollResetTask(taskId);
      } catch {
        setResetTask(null); // 错误由拦截器提示
      }
    } catch { /* 表单校验失败 */ }
  };

  return (
    <>
      <Button size="small" onClick={start}>
        串行控制台
      </Button>
      <Modal
        title={`串行控制台 - ${instanceName || instanceId}`}
        open={open}
        onCancel={handleClose}
        footer={
          <Space>
            <Button danger ghost size="small" onClick={() => { resetForm.setFieldsValue({ username: 'ubuntu' }); setResetOpen(true); }}>
              重置系统密码
            </Button>
            {conn && (
              <Button danger size="small" onClick={handleDelete}>
                删除此连接
              </Button>
            )}
            <Button size="small" onClick={handleClose}>关闭</Button>
          </Space>
        }
        width={860}
        destroyOnClose
      >
        <Text type="secondary" style={{ fontSize: 12 }}>
          通过 OCI 实例控制台连接直达串口，不依赖实例网络与 SSH 服务；串口出现 login 提示后输入系统用户名密码登录。
        </Text>
        {resetTask && (
          <div style={{ marginTop: 12, border: '1px solid #d9d9d9', borderRadius: 8, padding: 12 }}>
            <Space style={{ marginBottom: 8 }}>
              {resetTask.state === 'running' && <Spin size="small" />}
              <Text strong>自动重置密码</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>{resetTask.step}</Text>
              {resetTask.state === 'success' && <Text type="success">✅ 成功</Text>}
              {resetTask.state === 'failed' && <Text type="danger">❌ 失败：{resetTask.error}</Text>}
              {resetTask.state !== 'running' && (
                <Button size="small" type="link" onClick={() => setResetTask(null)}>清除</Button>
              )}
            </Space>
            <div
              ref={logBoxRef}
              style={{
                height: 180, overflowY: 'auto', background: '#0d1117', color: '#c9d1d9',
                borderRadius: 6, padding: 8, fontSize: 12, fontFamily: 'Menlo, Consolas, monospace',
                whiteSpace: 'pre-wrap',
              }}
            >
              {resetTask.logs.join('\n') || '等待任务开始…'}
            </div>
          </div>
        )}
        {(phase === 'creating') && (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin />
            <div style={{ marginTop: 12 }}>正在 OCI 创建控制台连接并等待就绪（约需 30~120 秒）…</div>
          </div>
        )}
        {phase === 'failed' && (
          <Alert type="error" showIcon style={{ marginTop: 12 }} message="连接失败" description={error} />
        )}
        {(phase === 'ready' || phase === 'connecting' || phase === 'connected') && (
          <div
            ref={termRef}
            style={{ height: 480, background: '#0d1117', borderRadius: 8, marginTop: 12, padding: 8 }}
          />
        )}
      </Modal>

      <Modal
        title="自动重置系统密码"
        open={resetOpen}
        onCancel={() => setResetOpen(false)}
        onOk={submitReset}
        okText="开始重置"
        okButtonProps={{ danger: true }}
        destroyOnClose
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="救砖操作，会硬重启实例"
          description="将通过串口自动执行：硬重启 → GRUB 单用户模式 → passwd 改密码 → 重启恢复，全程约 5~15 分钟。期间实例会中断服务，请确认实例当前已无法通过 SSH 登录再操作。密码仅用于本次任务，不会存储。"
        />
        <Form form={resetForm} layout="vertical" initialValues={{ username: 'ubuntu' }}>
          <Form.Item
            label="系统用户名"
            name="username"
            rules={[{ required: true, message: '请输入系统用户名' }]}
            extra="如 Ubuntu 系统填 ubuntu，Oracle Linux 填 opc"
          >
            <Input placeholder="ubuntu" />
          </Form.Item>
          <Form.Item
            label="新密码"
            name="new_password"
            rules={[{ required: true, message: '请输入新密码' }, { min: 6, message: '至少 6 位' }]}
          >
            <Input.Password placeholder="至少 6 位" />
          </Form.Item>
          <Form.Item
            label="确认新密码"
            name="confirm"
            rules={[{ required: true, message: '请再次输入新密码' }]}
          >
            <Input.Password placeholder="再次输入" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
