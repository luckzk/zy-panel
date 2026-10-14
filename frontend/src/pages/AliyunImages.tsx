import { useCallback, useEffect, useState } from 'react';
import {
  Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { listTenants, type TenantOption } from '../api/tenants';
import { createAliImage, deleteAliImage, listAliImages, type AliImage } from '../api/aliyun';
import { getProviderMeta } from '../providers/registry';

const meta = getProviderMeta('aliyun');

/** 阿里云镜像管理：自定义镜像列表 / 创建 / 删除 */
export default function AliyunImages() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number>();
  const [images, setImages] = useState<AliImage[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();

  useEffect(() => {
    listTenants().then((ts) => {
      const alis = ts.filter((t) => t.provider === 'aliyun');
      setTenants(alis);
      if (alis.length > 0) setTenantId(alis[0].id);
    }).catch(() => setTenants([]));
  }, []);

  const fetchImages = useCallback(async (tid: number) => {
    setLoading(true);
    try {
      setImages(await listAliImages(tid));
    } catch {
      message.error('查询失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tenantId !== undefined) fetchImages(tenantId);
  }, [tenantId, fetchImages]);

  const onFinish = async (values: Record<string, string>) => {
    if (tenantId === undefined) return;
    if (!values.instance_id && !values.snapshot_id) {
      message.warning('实例 ID 和快照 ID 至少填一个');
      return;
    }
    await createAliImage(tenantId, {
      instance_id: values.instance_id || undefined,
      snapshot_id: values.snapshot_id || undefined,
      name: values.name,
      description: values.description || '',
    });
    message.success('镜像创建已提交（需等待状态变为可用）');
    setModalOpen(false);
    fetchImages(tenantId);
  };

  const doDelete = async (im: AliImage) => {
    if (tenantId === undefined) return;
    await deleteAliImage(tenantId, im.id);
    message.success('镜像已删除');
    fetchImages(tenantId);
  };

  const columns: ColumnsType<AliImage> = [
    { title: '镜像名称', dataIndex: 'name', key: 'name', width: 220, ellipsis: true },
    { title: '镜像 ID', dataIndex: 'id', key: 'id', width: 200, ellipsis: true },
    { title: '操作系统', dataIndex: 'os_name', key: 'os', width: 200, ellipsis: true },
    { title: '架构', dataIndex: 'architecture', key: 'arch', width: 90 },
    { title: '大小', dataIndex: 'size_gb', key: 'size', width: 90, render: (v) => `${v} GB` },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 110,
      render: (v: string) => <Tag color={v === 'Available' ? 'green' : 'processing'}>{v}</Tag>,
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created', width: 170 },
    {
      title: '操作', key: 'op', width: 100, fixed: 'right',
      render: (_, r) => (
        <Popconfirm title={`确定删除镜像 ${r.name}？`} onConfirm={() => doDelete(r)}>
          <Button size="small" danger>删除</Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <Card
        title={
          <Space>
            镜像管理
            <Tag color={meta.color}>{meta.short}</Tag>
          </Space>
        }
        extra={<Button type="primary" disabled={tenantId === undefined} onClick={() => { form.resetFields(); setModalOpen(true); }}>创建镜像</Button>}
      >
        <Select
          style={{ width: 280, marginBottom: 16 }}
          placeholder="选择阿里云租户"
          value={tenantId}
          onChange={setTenantId}
          options={tenants.map((t) => ({ value: t.id, label: `${t.name}（${t.region}）` }))}
        />
        <Table<AliImage>
          rowKey="id" columns={columns} dataSource={images} loading={loading}
          scroll={{ x: 1300 }} pagination={{ showTotal: (t) => `共 ${t} 个自定义镜像` }}
        />
      </Card>

      <Modal
        title="创建自定义镜像"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={onFinish}>
          <Form.Item label="镜像名称" name="name" rules={[{ required: true }]}>
            <Input placeholder="如：web-server-20241014" />
          </Form.Item>
          <Form.Item label="来源实例 ID（与快照二选一）" name="instance_id" tooltip="从运行中/已停止的实例创建，需先停机保证数据一致性">
            <Input placeholder="i-xxxxxxxx" />
          </Form.Item>
          <Form.Item label="来源快照 ID（与实例二选一）" name="snapshot_id">
            <Input placeholder="s-xxxxxxxx" />
          </Form.Item>
          <Form.Item label="描述" name="description">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block>创建</Button>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
