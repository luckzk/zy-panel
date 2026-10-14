import { Card, Col, Row, Typography } from 'antd';
import SshTerminal from '../components/SshTerminal';

const { Text } = Typography;

/** Web SSH 终端（Cloud Shell 风格）页：复用 SshTerminal 组件 */
export default function TerminalPage() {
  return (
    <div>
      <Card title="Web SSH 终端" style={{ marginBottom: 16 }}>
        <SshTerminal height={560} />
      </Card>
      <Row style={{ marginTop: 8 }}>
        <Col>
          <Text type="secondary" style={{ fontSize: 12 }}>
            快捷入口：实例列表 → 详情 → Web 终端页签，主机已自动填入实例公网 IP（适合 SSH 直连场景）。
          </Text>
        </Col>
      </Row>
    </div>
  );
}
