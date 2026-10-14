import { Alert, Modal, Steps, Typography } from 'antd';

const { Text, Paragraph } = Typography;

/** 如何获取 OCI API 密钥：分步教程弹窗 */
export default function TenantApiGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal
      title="如何获取 OCI API 密钥"
      open={open}
      onCancel={onClose}
      footer={null}
      width={620}
      destroyOnClose
    >
      <Steps
        direction="vertical"
        size="small"
        items={[
          {
            title: '生成 API 密钥对',
            description: (
              <Paragraph style={{ marginBottom: 0 }}>
                登录 OCI 控制台 → 右上角头像 → <Text code>我的个人资料</Text> → 左侧 <Text code>API 密钥</Text> →
                <Text code>添加 API 密钥</Text> → 选择 <Text strong>生成 API 密钥对</Text> →
                点 <Text code>下载私钥</Text> 保存 .pem 文件 → <Text code>添加</Text>后复制显示的
                <Text strong>指纹</Text>（形如 <Text code>aa:bb:cc:…</Text> 共 16 组）。
                <Text type="secondary">私钥只在生成时可下载一次，丢了就删掉重建一对。</Text>
              </Paragraph>
            ),
          },
          {
            title: '复制 Tenancy OCID（租户 ID）',
            description: (
              <Paragraph style={{ marginBottom: 0 }}>
                右上角头像 → <Text code>租户：xxx</Text> → 租户信息页复制 <Text strong>OCID</Text>
               （以 <Text code>ocid1.tenancy.</Text> 开头）。
              </Paragraph>
            ),
          },
          {
            title: '复制 User OCID（用户 ID）',
            description: (
              <Paragraph style={{ marginBottom: 0 }}>
                右上角头像 → <Text code>我的个人资料</Text> → 复制 <Text strong>OCID</Text>
               （以 <Text code>ocid1.user.</Text> 开头）。注意是用户 OCID，不是租户 OCID。
              </Paragraph>
            ),
          },
          {
            title: '确认 Region（区域）',
            description: (
              <Paragraph style={{ marginBottom: 0 }}>
                看控制台地址栏的 <Text code>region</Text> 参数，如 <Text code>ap-tokyo-1</Text>（东京）、
                <Text code>ap-osaka-1</Text>（大阪）、<Text code>us-ashburn-1</Text> 等，
                在面板的 Region 下拉框选对应的即可。
              </Paragraph>
            ),
          },
          {
            title: '填回面板',
            description: (
              <Paragraph style={{ marginBottom: 0 }}>
                把 .pem 文件内容<Text strong>完整粘贴</Text>到「Private Key」框
               （包含 <Text code>-----BEGIN PRIVATE KEY-----</Text> 首尾行），
                其他字段按上面复制的内容填写，保存后点 <Text code>测试连接</Text>验证。
              </Paragraph>
            ),
          },
        ]}
      />
      <Alert
        type="info"
        showIcon
        style={{ marginTop: 12 }}
        message="私钥在面板中经加密存储，列表和日志里不会明文展示；一个用户可有多对 API 密钥，面板用哪对就填哪对。"
      />
    </Modal>
  );
}
