import { useEffect, useState } from 'react';
import { Alert, Checkbox, Modal, Typography } from 'antd';

const { Text } = Typography;

interface TerminateInstanceModalProps {
  open: boolean;
  instanceName?: string;
  confirmLoading?: boolean;
  onCancel: () => void;
  /** deleteBootVolume=true 表示连引导卷一起删除 */
  onConfirm: (deleteBootVolume: boolean) => void;
}

/** 终止实例确认弹窗（声明式 Modal：antd 5.29 + React 19 下静态 Modal.confirm 不渲染） */
export default function TerminateInstanceModal({
  open,
  instanceName,
  confirmLoading,
  onCancel,
  onConfirm,
}: TerminateInstanceModalProps) {
  const [deleteBootVolume, setDeleteBootVolume] = useState(false);

  // 每次打开都回到默认：不删除引导卷
  useEffect(() => {
    if (open) setDeleteBootVolume(false);
  }, [open]);

  return (
    <Modal
      open={open}
      title="终止实例"
      okText="确认终止"
      okButtonProps={{ danger: true, loading: confirmLoading }}
      cancelText="取消"
      onCancel={onCancel}
      onOk={() => onConfirm(deleteBootVolume)}
      destroyOnClose
    >
      <p>
        确定终止实例 <Text strong>{instanceName ?? ''}</Text> 吗？此操作不可恢复！
      </p>
      <Checkbox checked={deleteBootVolume} onChange={(e) => setDeleteBootVolume(e.target.checked)}>
        同时删除引导卷
      </Checkbox>
      {deleteBootVolume ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 12 }}
          message="引导卷将一并删除，且无法恢复，也无法再用于从引导卷抢机。"
        />
      ) : (
        <Alert
          type="info"
          showIcon
          style={{ marginTop: 12 }}
          message="引导卷将保留，可用于救援数据或从引导卷抢机。"
        />
      )}
    </Modal>
  );
}
