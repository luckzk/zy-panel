import { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Modal,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import { CopyOutlined, QrcodeOutlined, SafetyOutlined } from '@ant-design/icons';
import {
  changePassword,
  me,
  mfaDisable,
  mfaSetup,
  mfaStatus,
  mfaVerify,
  type MeInfo,
  type MfaSetupResult,
} from '../api/auth';

const { Text } = Typography;

/** 安全设置：MFA 两步验证绑定/解绑 + 修改密码 */
export default function MfaSettings() {
  const [loading, setLoading] = useState(true);
  const [info, setInfo] = useState<MeInfo | null>(null);
  const [mfaEnabled, setMfaEnabled] = useState(false);

  /** 绑定流程中的二维码与密钥 */
  const [binding, setBinding] = useState<MfaSetupResult | null>(null);
  const [bindCode, setBindCode] = useState('');
  const [bindBusy, setBindBusy] = useState(false);

  /** 解绑弹窗 */
  const [disableOpen, setDisableOpen] = useState(false);
  const [disableCode, setDisableCode] = useState('');
  const [disableBusy, setDisableBusy] = useState(false);

  const [pwdForm] = Form.useForm();

  const refresh = async () => {
    try {
      const [mine, status] = await Promise.all([me(), mfaStatus()]);
      setInfo(mine);
      setMfaEnabled(status.mfa_enabled);
    } catch {
      /* 拦截器已提示 */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  /** 开始绑定：生成二维码（会覆盖未生效的旧密钥） */
  const startBind = async () => {
    setBindBusy(true);
    try {
      const result = await mfaSetup();
      setBinding(result);
      setBindCode('');
    } catch {
      /* 拦截器已提示 */
    } finally {
      setBindBusy(false);
    }
  };

  /** 验证并启用 */
  const confirmBind = async () => {
    if (!/^\d{6}$/.test(bindCode)) {
      message.warning('请输入 6 位数字验证码');
      return;
    }
    setBindBusy(true);
    try {
      await mfaVerify(bindCode);
      message.success('MFA 已启用，登录时需要输入验证码');
      setBinding(null);
      setBindCode('');
      await refresh();
    } catch {
      /* 拦截器已提示 */
    } finally {
      setBindBusy(false);
    }
  };

  /** 解绑确认 */
  const confirmDisable = async () => {
    if (!/^\d{6}$/.test(disableCode)) {
      message.warning('请输入 6 位数字验证码');
      return;
    }
    setDisableBusy(true);
    try {
      await mfaDisable(disableCode);
      message.success('MFA 已关闭');
      setDisableOpen(false);
      setDisableCode('');
      await refresh();
    } catch {
      /* 拦截器已提示 */
    } finally {
      setDisableBusy(false);
    }
  };

  const copySecret = async () => {
    if (!binding) return;
    try {
      await navigator.clipboard.writeText(binding.secret);
      message.success('密钥已复制');
    } catch {
      message.error('复制失败，请手动记录');
    }
  };

  /** 修改密码 */
  const onChangePassword = async (values: { oldPassword: string; newPassword: string }) => {
    try {
      await changePassword(values.oldPassword, values.newPassword);
      message.success('密码修改成功，请重新登录');
      pwdForm.resetFields();
    } catch {
      /* 拦截器已提示 */
    }
  };

  if (loading) {
    return (
      <Card style={{ maxWidth: 720 }}>
        <Spin />
      </Card>
    );
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%', maxWidth: 720 }}>
      <Card
        title={
          <Space>
            <SafetyOutlined />
            <span>MFA 两步验证</span>
            <Tag color={mfaEnabled ? 'success' : 'default'}>{mfaEnabled ? '已启用' : '未启用'}</Tag>
          </Space>
        }
      >
        <Descriptions size="small" column={1} style={{ marginBottom: 16 }}>
          <Descriptions.Item label="当前用户">{info?.username}</Descriptions.Item>
          <Descriptions.Item label="角色">{info?.is_admin ? '管理员' : '普通用户'}</Descriptions.Item>
        </Descriptions>

        {!mfaEnabled && !binding && (
          <Space direction="vertical">
            <Text type="secondary">
              绑定后登录时需要再输入一次手机验证器（Google Authenticator / 1Password 等）上的 6
              位动态码，防止密码泄露导致账号被盗。
            </Text>
            <Button type="primary" icon={<QrcodeOutlined />} loading={bindBusy} onClick={startBind}>
              开始绑定
            </Button>
          </Space>
        )}

        {!mfaEnabled && binding && (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Alert
              type="warning"
              showIcon
              message="请在验证通过前妥善保管密钥，绑定成功后密钥不再展示"
            />
            <div style={{ textAlign: 'center' }}>
              <img
                src={binding.qr_data_uri}
                alt="MFA 绑定二维码"
                style={{ width: 200, height: 200, border: '1px solid #f0f0f0', borderRadius: 8 }}
              />
              <div style={{ marginTop: 8 }}>
                <Text type="secondary">无法扫码时可手动输入密钥：</Text>
                <br />
                <Text code copyable={false} style={{ fontSize: 14, letterSpacing: 1 }}>
                  {binding.secret}
                </Text>
                <Button
                  type="link"
                  size="small"
                  icon={<CopyOutlined />}
                  onClick={copySecret}
                >
                  复制
                </Button>
              </div>
            </div>
            <Space>
              <Input.OTP length={6} value={bindCode} onChange={setBindCode} />
              <Button type="primary" loading={bindBusy} onClick={confirmBind}>
                验证并启用
              </Button>
              <Button onClick={() => setBinding(null)}>取消</Button>
            </Space>
          </Space>
        )}

        {mfaEnabled && (
          <Space direction="vertical">
            <Alert
              type="success"
              showIcon
              message="两步验证已启用，登录时需要输入验证器上的动态码"
            />
            <Button danger onClick={() => setDisableOpen(true)}>
              解绑 MFA
            </Button>
          </Space>
        )}
      </Card>

      <Card title="修改密码">
        <Form form={pwdForm} layout="vertical" onFinish={onChangePassword} style={{ maxWidth: 400 }}>
          <Form.Item
            name="oldPassword"
            label="原密码"
            rules={[{ required: true, message: '请输入原密码' }]}
          >
            <Input.Password placeholder="当前登录密码" />
          </Form.Item>
          <Form.Item
            name="newPassword"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, message: '新密码至少 6 位' },
            ]}
          >
            <Input.Password placeholder="至少 6 位" />
          </Form.Item>
          <Form.Item
            name="confirmPassword"
            label="确认新密码"
            dependencies={['newPassword']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('newPassword') === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error('两次输入的新密码不一致'));
                },
              }),
            ]}
          >
            <Input.Password placeholder="再次输入新密码" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit">
              修改密码
            </Button>
          </Form.Item>
        </Form>
      </Card>

      <Modal
        title="解绑 MFA"
        open={disableOpen}
        confirmLoading={disableBusy}
        onOk={confirmDisable}
        onCancel={() => setDisableOpen(false)}
        okText="确认解绑"
        okButtonProps={{ danger: true }}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Text type="secondary">
            解绑后登录将不再需要动态码。请先输入验证器上的当前验证码确认是本人操作：
          </Text>
          <Input.OTP length={6} value={disableCode} onChange={setDisableCode} />
        </Space>
      </Modal>
    </Space>
  );
}
