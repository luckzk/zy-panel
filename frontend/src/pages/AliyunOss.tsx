import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Breadcrumb,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import { DeleteOutlined, DownloadOutlined, FolderOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { listTenants, listTenantRegions, type TenantOption } from '../api/tenants';
import {
  createAliOssBucket,
  deleteAliOssBucket,
  deleteAliOssObject,
  getAliOssDownloadUrl,
  listAliOssBuckets,
  listAliOssObjects,
  uploadAliOssObject,
  type AliOssBucket,
  type AliOssObject,
} from '../api/aliyun';

const { Text } = Typography;

/** 大小格式化：B/KB/MB/GB */
function formatSize(bytes: number): string {
  if (!bytes || bytes <= 0) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`;
}

/** OSS 对象存储：Bucket 列表 + 文件浏览（上传/下载/删除） */
export default function AliyunOss() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<number>();
  const [regions, setRegions] = useState<{ value: string; label: string }[]>([]);
  const [buckets, setBuckets] = useState<AliOssBucket[]>([]);
  const [bucketName, setBucketName] = useState<string>();
  const [prefix, setPrefix] = useState(''); // 当前目录前缀，结尾带 /
  const [objects, setObjects] = useState<AliOssObject[]>([]);
  const [bucketsLoading, setBucketsLoading] = useState(false);
  const [objectsLoading, setObjectsLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [tenantsLoaded, setTenantsLoaded] = useState(false);
  const [bucketOpen, setBucketOpen] = useState(false);
  const [bucketRegion, setBucketRegion] = useState<string>();
  const [bucketForm] = Form.useForm<{ name: string }>();
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listTenants()
      .then((ts) => {
        const ali = ts.filter((t) => t.provider === 'aliyun');
        setTenants(ali);
        if (ali.length > 0) setTenantId(ali[0].id);
      })
      .catch(() => setTenants([]))
      .finally(() => setTenantsLoaded(true));
  }, []);

  // 地域列表：运行时拉取（新建 Bucket 时选地域）
  useEffect(() => {
    if (tenantId === undefined) return;
    listTenantRegions(tenantId)
      .then((rs) => setRegions(rs.map((r) => ({ value: r.id, label: `${r.name}（${r.id}）` }))))
      .catch(() => setRegions([]));
  }, [tenantId]);

  const fetchBuckets = useCallback(async (tid: number) => {
    setBucketsLoading(true);
    try {
      const bs = await listAliOssBuckets(tid);
      setBuckets(bs);
      setBucketName((cur) => (bs.some((b) => b.name === cur) ? cur : bs[0]?.name));
    } catch {
      setBuckets([]);
      message.error('Bucket 查询失败');
    } finally {
      setBucketsLoading(false);
    }
  }, []);

  const fetchObjects = useCallback(async (tid: number, bucket: string, pfx: string) => {
    setObjectsLoading(true);
    try {
      setObjects(await listAliOssObjects(tid, bucket, pfx));
    } catch {
      setObjects([]);
      message.error('文件列表查询失败');
    } finally {
      setObjectsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tenantId !== undefined) {
      setPrefix('');
      fetchBuckets(tenantId);
    }
  }, [tenantId, fetchBuckets]);

  useEffect(() => {
    if (tenantId !== undefined && bucketName) fetchObjects(tenantId, bucketName, prefix);
    else setObjects([]);
  }, [tenantId, bucketName, prefix, fetchObjects]);

  /** 面包屑路径段 */
  const crumbs = useMemo(() => prefix.split('/').filter(Boolean), [prefix]);

  const enterDir = (dirKey: string) => setPrefix(dirKey);
  const goCrumb = (idx: number) => setPrefix(idx < 0 ? '' : `${crumbs.slice(0, idx + 1).join('/')}/`);

  const onCreateBucket = async () => {
    if (tenantId === undefined) return;
    const v = await bucketForm.validateFields();
    await createAliOssBucket(tenantId, v.name.trim(), bucketRegion);
    message.success(`Bucket ${v.name.trim()} 已创建`);
    setBucketOpen(false);
    bucketForm.resetFields();
    setBucketRegion(undefined);
    fetchBuckets(tenantId);
  };

  const onDeleteBucket = async (name: string) => {
    if (tenantId === undefined) return;
    await deleteAliOssBucket(tenantId, name);
    message.success(`Bucket ${name} 已删除`);
    if (bucketName === name) {
      setBucketName(undefined);
      setPrefix('');
    }
    fetchBuckets(tenantId);
  };

  const onDeleteObject = async (key: string) => {
    if (tenantId === undefined || !bucketName) return;
    await deleteAliOssObject(tenantId, bucketName, key);
    message.success('已删除');
    fetchObjects(tenantId, bucketName, prefix);
  };

  const onDownload = async (key: string) => {
    if (tenantId === undefined || !bucketName) return;
    try {
      const url = await getAliOssDownloadUrl(tenantId, bucketName, key);
      window.open(url, '_blank');
    } catch {
      message.error('获取下载链接失败');
    }
  };

  /** 隐藏 input 触发文件选择，手动调上传接口（避免 Upload 组件自动上传行为） */
  const onPickFile = () => fileInputRef.current?.click();

  const onFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // 允许重复选同一文件
    if (!file || tenantId === undefined || !bucketName) return;
    setUploading(true);
    try {
      await uploadAliOssObject(tenantId, bucketName, file, prefix);
      message.success(`已上传：${file.name}`);
      fetchObjects(tenantId, bucketName, prefix);
    } catch {
      message.error('上传失败');
    } finally {
      setUploading(false);
    }
  };

  /** 显示名：去掉 prefix 前缀 */
  const displayName = (key: string) => {
    const rest = key.startsWith(prefix) ? key.slice(prefix.length) : key;
    return rest.replace(/\/$/, '');
  };

  const columns: ColumnsType<AliOssObject> = [
    {
      title: '名称',
      dataIndex: 'key',
      key: 'key',
      ellipsis: true,
      render: (key: string, r: AliOssObject) =>
        r.type === 'dir' ? (
          <Button type="link" icon={<FolderOutlined />} onClick={() => enterDir(key)} style={{ padding: 0 }}>
            {displayName(key)}
          </Button>
        ) : (
          <Text>{displayName(key)}</Text>
        ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 90,
      render: (v: string) => (v === 'dir' ? <Tag color="blue">目录</Tag> : <Tag>文件</Tag>),
    },
    {
      title: '大小',
      dataIndex: 'size',
      key: 'size',
      width: 120,
      render: (v: number, r: AliOssObject) => (r.type === 'dir' ? '-' : formatSize(v)),
    },
    { title: '修改时间', dataIndex: 'last_modified', key: 'last_modified', width: 190 },
    {
      title: '操作',
      key: 'action',
      width: 170,
      render: (_, r) =>
        r.type === 'dir' ? (
          <Text type="secondary">-</Text>
        ) : (
          <Space size="small">
            <Button size="small" icon={<DownloadOutlined />} onClick={() => onDownload(r.key)}>
              下载
            </Button>
            <Popconfirm title={`确定删除 ${displayName(r.key)} 吗？`} onConfirm={() => onDeleteObject(r.key)}>
              <Button size="small" danger icon={<DeleteOutlined />}>
                删除
              </Button>
            </Popconfirm>
          </Space>
        ),
    },
  ];

  if (tenantsLoaded && tenants.length === 0) {
    return (
      <Card title="OSS 对象存储">
        <Empty description="还没有阿里云租户，请先添加" />
      </Card>
    );
  }

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          style={{ width: 240 }}
          placeholder="选择阿里云租户"
          value={tenantId}
          onChange={setTenantId}
          options={tenants.map((t) => ({ value: t.id, label: t.name }))}
        />
      </Space>
      <Row gutter={16}>
        <Col xs={24} md={8} lg={7}>
          <Card
            title="Bucket"
            loading={bucketsLoading}
            extra={
              <Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => setBucketOpen(true)}>
                新建 Bucket
              </Button>
            }
          >
            {buckets.length === 0 && !bucketsLoading ? (
              <Empty description="暂无 Bucket，点击右上角新建" />
            ) : (
              <List
                dataSource={buckets}
                renderItem={(b) => (
                  <List.Item
                    style={{
                      cursor: 'pointer',
                      background: b.name === bucketName ? '#e6f4ff' : undefined,
                      borderRadius: 6,
                      padding: '8px 12px',
                    }}
                    onClick={() => {
                      setBucketName(b.name);
                      setPrefix('');
                    }}
                    actions={[
                      <Popconfirm
                        key="del"
                        title={`确定删除 Bucket ${b.name} 吗？（需先清空文件）`}
                        onConfirm={(e) => {
                          e?.stopPropagation();
                          onDeleteBucket(b.name);
                        }}
                        onCancel={(e) => e?.stopPropagation()}
                      >
                        <Button
                          size="small"
                          danger
                          type="text"
                          icon={<DeleteOutlined />}
                          onClick={(e) => e.stopPropagation()}
                        />
                      </Popconfirm>,
                    ]}
                  >
                    <List.Item.Meta
                      title={<Text strong={b.name === bucketName}>{b.name}</Text>}
                      description={`${b.location || ''} · ${b.storage_class || ''}`}
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} md={16} lg={17}>
          <Card
            title={
              <Breadcrumb
                items={[
                  { title: <a onClick={() => goCrumb(-1)}>根目录</a> },
                  ...crumbs.map((c, i) => ({ title: <a onClick={() => goCrumb(i)}>{c}</a> })),
                ]}
              />
            }
            extra={
              <Space>
                <input ref={fileInputRef} type="file" style={{ display: 'none' }} onChange={onFileChange} />
                <Button
                  type="primary"
                  icon={<UploadOutlined />}
                  onClick={onPickFile}
                  loading={uploading}
                  disabled={!bucketName}
                >
                  上传文件
                </Button>
                <Button
                  onClick={() => tenantId !== undefined && bucketName && fetchObjects(tenantId, bucketName, prefix)}
                  loading={objectsLoading}
                >
                  刷新
                </Button>
              </Space>
            }
          >
            {!bucketName ? (
              <Empty description="请先选择左侧 Bucket" />
            ) : (
              <Table<AliOssObject>
                rowKey="key"
                columns={columns}
                dataSource={objects}
                loading={objectsLoading || uploading}
                pagination={{ showSizeChanger: true, showTotal: (t) => `共 ${t} 项` }}
                locale={{ emptyText: '该目录为空，可点击右上角上传文件' }}
              />
            )}
          </Card>
        </Col>
      </Row>
      <Modal
        title="新建 Bucket"
        open={bucketOpen}
        onCancel={() => setBucketOpen(false)}
        onOk={onCreateBucket}
        okText="创建"
        destroyOnClose
      >
        <Form form={bucketForm} layout="vertical">
          <Form.Item
            name="name"
            label="Bucket 名称"
            rules={[
              { required: true, message: '请输入 Bucket 名称' },
              {
                pattern: /^[a-z0-9-]{3,63}$/,
                message: '3-63 个字符，仅小写字母、数字、横线',
              },
            ]}
          >
            <Input placeholder="如：my-backup-bucket" />
          </Form.Item>
          <Form.Item label="地域">
            <Select
              placeholder="不选则使用账号默认地域"
              allowClear
              value={bucketRegion}
              onChange={setBucketRegion}
              options={regions}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
