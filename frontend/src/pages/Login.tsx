import axios from 'axios';
import { useState } from 'react';
import { Button, Card, Form, Input, Typography, message } from 'antd';
import { LockOutlined, SafetyOutlined, UserOutlined } from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../stores/auth';
import { useThemeStore } from '../stores/theme';
import { api, setToken } from '../api/client';

const { Title, Paragraph, Text } = Typography;

/** 与后端 auth.MFA_REQUIRED_MSG 保持一致：拦截器把业务码转为 Error(message) */
const MFA_REQUIRED_MSG = '需要 MFA 验证码';
const USER_KEY = 'oci_panel_user';

interface LoginForm {
  username: string;
  password: string;
  mfa_code?: string;
}

/** 登录页：用户名密码表单；账号启用 MFA 时自动进入第二阶段验证码输入 */
export default function Login() {
  const [loading, setLoading] = useState(false);
  const [mfaRequired, setMfaRequired] = useState(false);
  const [form] = Form.useForm<LoginForm>();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? '/dashboard';
  const futuristic = useThemeStore((s) => s.mode) === 'futuristic';

  /** 登录成功：写 token + 同步 zustand 状态 + 跳转 */
  const finishLogin = (token: string, username: string) => {
    setToken(token);
    const user = { username };
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    useAuthStore.setState({ token, user });
    message.success(`欢迎回来，${username}`);
    navigate(from, { replace: true });
  };

  const doLogin = async (values: LoginForm) => {
    setLoading(true);
    try {
      const resp = await api.post('/api/v1/auth/login', {
        username: values.username,
        password: values.password,
        ...(values.mfa_code ? { mfa_code: values.mfa_code } : {}),
      });
      const { token, username } = resp.data as { token: string; username: string };
      finishLogin(token, username);
    } catch (e) {
      // 完全连不上后端（无 response）：明确报错，不再静默进入演示模式
      if (axios.isAxiosError(e) && !e.response) {
        message.error('无法连接后端服务，请检查后端是否已启动');
        return;
      }
      // 后端要求 MFA 二次校验：切换到验证码输入阶段（toast 已由拦截器弹出）
      if (e instanceof Error && e.message === MFA_REQUIRED_MSG) {
        setMfaRequired(true);
      }
      // 其他业务错误已由 axios 拦截器统一提示
    } finally {
      setLoading(false);
    }
  };

  /** 返回账号密码阶段 */
  const backToAccount = () => {
    setMfaRequired(false);
    form.setFieldsValue({ mfa_code: undefined });
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: futuristic ? 'transparent' : 'linear-gradient(135deg, #001529 0%, #003a5c 100%)',
      }}
    >
      <Card style={{ width: 380 }} bordered={false}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <img src="/favicon.svg" alt="zy-panel" style={{ width: 52, height: 52, marginBottom: 8 }} />
          <Title level={3} style={{ marginBottom: 4 }}>
            zy-panel
          </Title>
          <Paragraph type="secondary">多云服务器管理面板</Paragraph>
        </div>
        <Form<LoginForm> form={form} name="login" initialValues={{}} onFinish={doLogin} size="large">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]} hidden={mfaRequired}>
            <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]} hidden={mfaRequired}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
          </Form.Item>

          {mfaRequired && (
            <>
              <div style={{ textAlign: 'center', marginBottom: 16 }}>
                <SafetyOutlined style={{ fontSize: 32, color: '#1677ff' }} />
                <Paragraph style={{ marginTop: 8, marginBottom: 4 }}>
                  <Text strong>两步验证</Text>
                </Paragraph>
                <Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 0 }}>
                  该账号已启用 MFA，请输入验证器 App 中的 6 位验证码
                </Paragraph>
              </div>
              <Form.Item
                name="mfa_code"
                rules={[
                  { required: true, message: '请输入 6 位验证码' },
                  { pattern: /^\d{6}$/, message: '验证码为 6 位数字' },
                ]}
              >
                <Input.OTP
                  length={6}
                  autoFocus
                  style={{ justifyContent: 'center' }}
                  onChange={(v) => {
                    if (v.length === 6 && !loading) form.submit();
                  }}
                />
              </Form.Item>
            </>
          )}

          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>
              {mfaRequired ? '验证并登录' : '登录'}
            </Button>
          </Form.Item>
          {mfaRequired && (
            <Form.Item style={{ marginBottom: 0, textAlign: 'center' }}>
              <Button type="link" onClick={backToAccount}>
                返回修改账号
              </Button>
            </Form.Item>
          )}
        </Form>
        <Paragraph type="secondary" style={{ fontSize: 12, textAlign: 'center', marginBottom: 0 }}>
          默认账号 admin / admin123，登录后请及时修改密码
        </Paragraph>
      </Card>
    </div>
  );
}
