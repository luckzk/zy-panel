import { useEffect, useRef, useState } from 'react';
import { Button, Form, Input, InputNumber, Select, Space, Typography, message } from 'antd';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';

const { Text } = Typography;

interface ConnForm {
  host: string;
  port: number;
  username: string;
  auth_type: 'password' | 'key';
  credential: string;
}

interface SshTerminalProps {
  /** 预填的主机 IP（可空，由用户填写） */
  defaultHost?: string;
  /** 预填的用户名 */
  defaultUsername?: string;
  /** 终端高度 */
  height?: number;
  /** 是否显示连接表单（false 则只渲染终端区，由外部调用 connect） */
  showForm?: boolean;
}

/** 从 localStorage 取登录 token，用于 ws 鉴权 */
function getToken(): string {
  return localStorage.getItem('oci_panel_token') || '';
}

/**
 * 可复用的 Web SSH 终端：xterm.js + 后端 /ws/terminal 桥接。
 * 凭证仅用于本次连接，不存储。
 */
export default function SshTerminal({
  defaultHost = '',
  defaultUsername = 'opc',
  height = 480,
  showForm = true,
}: SshTerminalProps) {
  const [form] = Form.useForm<ConnForm>();
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const termRef = useRef<HTMLDivElement>(null);
  const term = useRef<Terminal | null>(null);
  const ws = useRef<WebSocket | null>(null);

  const dispose = () => {
    try { ws.current?.close(); } catch { /* ignore */ }
    ws.current = null;
    term.current?.dispose();
    term.current = null;
    setConnected(false);
  };

  useEffect(() => dispose, []);
  // defaultHost 变化时同步到表单（实例详情切换实例时）
  useEffect(() => {
    if (defaultHost) form.setFieldValue('host', defaultHost);
  }, [defaultHost, form]);

  const connect = async (values: ConnForm) => {
    dispose();
    setConnecting(true);
    const t = new Terminal({
      cursorBlink: true,
      fontSize: 14,
      fontFamily: 'Menlo, Consolas, monospace',
      theme: { background: '#0d1117' },
    });
    term.current = t;
    if (termRef.current) {
      t.open(termRef.current);
      t.writeln('正在连接…');
    }
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    // /ws/ 由 nginx 反代到后端并升级为 WebSocket
    const url = `${proto}://${window.location.host}/ws/terminal?token=${encodeURIComponent(getToken())}`;
    const socket = new WebSocket(url);
    ws.current = socket;

    socket.onopen = () => {
      socket.send(JSON.stringify({
        type: 'connect',
        host: values.host.trim(),
        port: values.port || 22,
        username: values.username.trim(),
        auth_type: values.auth_type,
        credential: values.credential,
      }));
    };
    socket.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'output') {
          t.write(msg.data);
          if (!connected) { setConnected(true); setConnecting(false); }
        } else if (msg.type === 'error') {
          t.writeln(`\r\n❌ ${msg.message}`);
          message.error(msg.message);
          setConnecting(false);
        } else if (msg.type === 'closed') {
          t.writeln('\r\n连接已关闭');
          setConnected(false);
        }
      } catch { /* ignore */ }
    };
    socket.onerror = () => {
      t.writeln('\r\n❌ WebSocket 连接失败');
      setConnecting(false);
    };
    socket.onclose = () => setConnected(false);

    t.onData((data) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'input', data }));
      }
    });
  };

  return (
    <div>
      {showForm && (
        <>
          <Form<ConnForm>
            form={form}
            layout="inline"
            onFinish={connect}
            initialValues={{ port: 22, username: defaultUsername, auth_type: 'password', host: defaultHost }}
            style={{ rowGap: 12, marginBottom: 12 }}
          >
            <Form.Item name="host" label="主机" rules={[{ required: true, message: '请输入主机 IP/域名' }]}>
              <Input placeholder="如：150.136.12.34" style={{ width: 170 }} />
            </Form.Item>
            <Form.Item name="port" label="端口">
              <InputNumber min={1} max={65535} style={{ width: 80 }} />
            </Form.Item>
            <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
              <Input placeholder="opc / ubuntu / root" style={{ width: 130 }} />
            </Form.Item>
            <Form.Item name="auth_type" label="认证">
              <Select
                style={{ width: 100 }}
                options={[
                  { label: '密码', value: 'password' },
                  { label: '私钥', value: 'key' },
                ]}
              />
            </Form.Item>
            <Form.Item
              noStyle
              shouldUpdate={(prev, cur) => prev.auth_type !== cur.auth_type}
            >
              {({ getFieldValue }) =>
                getFieldValue('auth_type') === 'key' ? (
                  <Form.Item name="credential" label="私钥" rules={[{ required: true }]}>
                    <Input.TextArea rows={1} placeholder="-----BEGIN PRIVATE KEY-----" style={{ width: 220 }} />
                  </Form.Item>
                ) : (
                  <Form.Item name="credential" label="密码" rules={[{ required: true }]}>
                    <Input.Password style={{ width: 160 }} />
                  </Form.Item>
                )
              }
            </Form.Item>
            <Form.Item>
              <Space>
                <Button type="primary" htmlType="submit" loading={connecting} disabled={connected}>
                  {connected ? '已连接' : '连接'}
                </Button>
                {connected && <Button onClick={dispose}>断开</Button>}
              </Space>
            </Form.Item>
          </Form>
          <Text type="secondary" style={{ fontSize: 12 }}>
            凭证仅用于本次 SSH 连接，不会存储。连接经后端中转，请确保后端服务器能访问目标主机。
          </Text>
        </>
      )}
      <div
        ref={termRef}
        style={{ height, padding: 8, background: '#0d1117', borderRadius: 8, marginTop: showForm ? 12 : 0 }}
      />
    </div>
  );
}
