import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  message,
} from 'antd';
import { PlayCircleOutlined, PlusOutlined, SearchOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { listTenants, type TenantOption } from '../api/tenants';
import { listInstances } from '../api/instances';
import {
  createScheduledTask,
  deleteScheduledTask,
  getTaskTypes,
  listScheduledTasks,
  runScheduledTaskNow,
  toggleScheduledTask,
  updateScheduledTask,
  type ScheduledTask,
  type TaskTypeOption,
} from '../api/scheduled';

const WEEKDAYS: Record<string, string> = {
  '0': '周日', '7': '周日', '1': '周一', '2': '周二', '3': '周三', '4': '周四', '5': '周五', '6': '周六',
};

/** cron 5 段转中文描述（常用模式，兜底显示原文） */
export function describeCron(expr: string): string {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return expr;
  const [mi, hr, dom, mon, dow] = parts;
  const pad = (s: string) => s.padStart(2, '0');
  const timePart =
    hr === '*'
      ? mi === '*'
        ? '每分钟'
        : mi.startsWith('*/')
          ? `每 ${mi.slice(2)} 分钟`
          : `每小时 ${mi} 分`
      : hr.startsWith('*/')
        ? `每 ${hr.slice(2)} 小时`
        : mi === '0'
          ? `${hr}:00`
          : `${hr}:${pad(mi)}`;
  let datePart = '每天';
  if (dow !== '*') {
    if (dow === '1-5') datePart = '每个工作日';
    else if (dow === '0' || dow === '7') datePart = '每周日';
    else if (dow === '6') datePart = '每周六';
    else {
      const names = dow.split(',').map((d) => WEEKDAYS[d] ?? d);
      datePart = `每${names.join('、')}`;
    }
  } else if (dom !== '*') {
    datePart = dom.startsWith('*/') ? `每 ${dom.slice(2)} 天` : `每月 ${dom} 日`;
  }
  const monPart = mon === '*' ? '' : `${mon} 月`;
  if (timePart === '每分钟' || timePart.startsWith('每 ')) return `${datePart}${timePart}`;
  return `${monPart}${datePart} ${timePart}`;
}

/** 常用 cron 模板 */
const CRON_TEMPLATES: { label: string; cron: string; task_type?: string }[] = [
  { label: '每天 2:00 关机', cron: '0 2 * * *', task_type: 'power_off' },
  { label: '每天 9:00 开机', cron: '0 9 * * *', task_type: 'power_on' },
  { label: '工作日 9:00 开机', cron: '0 9 * * 1-5', task_type: 'power_on' },
  { label: '工作日 19:00 关机', cron: '0 19 * * 1-5', task_type: 'power_off' },
  { label: '每周日 3:00 换 IP', cron: '0 3 * * 0', task_type: 'change_ip' },
  { label: '每小时整点', cron: '0 * * * *' },
];

/** 后端 naive UTC 时间转本地显示 */
function fmtTime(iso: string | null): string {
  if (!iso) return '-';
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false });
}

interface FormValues {
  name: string;
  tenant_id: number;
  instance_id: string;
  task_type: string;
  cron_expr: string;
  enabled: boolean;
}

/** 定时任务页：cron 驱动的定时开关机 / 定时换 IP */
export default function ScheduledTasks() {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [taskTypes, setTaskTypes] = useState<TaskTypeOption[]>([]);
  const [list, setList] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<ScheduledTask | null>(null);
  const [instances, setInstances] = useState<{ id: string; name: string }[]>([]);
  const [instLoading, setInstLoading] = useState(false);
  const [instanceNameMap, setInstanceNameMap] = useState<Record<string, string>>({});
  const [form] = Form.useForm<FormValues>();
  const tenantId = Form.useWatch('tenant_id', form);
  const cronExpr = Form.useWatch('cron_expr', form);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [ts, types, tasks] = await Promise.all([
        listTenants(),
        getTaskTypes().catch(() => [] as TaskTypeOption[]),
        listScheduledTasks(),
      ]);
      setTenants(ts);
      setTaskTypes(types);
      setList(tasks);
      // 为表格展示解析实例名（各租户并行拉取）
      const maps = await Promise.all(
        ts.map(async (t) => {
          try {
            const { items } = await listInstances({ tenant_id: t.id, page_size: 200 }, t.name);
            return items.map((i) => [i.id, i.name] as [string, string]);
          } catch {
            return [] as [string, string][];
          }
        }),
      );
      setInstanceNameMap(Object.fromEntries(maps.flat()));
    } catch {
      setList([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  // 新建/编辑 Modal 中按租户加载实例下拉
  useEffect(() => {
    if (!open || !tenantId) {
      setInstances([]);
      return;
    }
    const t = tenants.find((x) => x.id === tenantId);
    setInstLoading(true);
    listInstances({ tenant_id: tenantId, page_size: 200 }, t?.name ?? '')
      .then(({ items }) => setInstances(items.map((i) => ({ id: i.id, name: i.name }))))
      .catch(() => setInstances([]))
      .finally(() => setInstLoading(false));
  }, [open, tenantId, tenants]);

  const filtered = useMemo(
    () => list.filter((t) => !keyword || t.name.includes(keyword)),
    [list, keyword],
  );

  const doAction = async (fn: () => Promise<unknown>, okMsg: string) => {
    try {
      await fn();
      message.success(okMsg);
      fetchAll();
    } catch {
      /* 错误已由拦截器提示 */
    }
  };

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ enabled: true, task_type: 'power_off' });
    setOpen(true);
  };

  const openEdit = (record: ScheduledTask) => {
    setEditing(record);
    form.setFieldsValue({
      name: record.name,
      tenant_id: record.tenant_id,
      instance_id: record.instance_id,
      task_type: record.task_type,
      cron_expr: record.cron_expr,
      enabled: record.enabled,
    });
    setOpen(true);
  };

  const onFinish = async (values: FormValues) => {
    const body = {
      name: values.name,
      tenant_id: values.tenant_id,
      instance_id: values.instance_id,
      task_type: values.task_type,
      cron_expr: values.cron_expr.trim(),
      enabled: values.enabled ?? true,
    };
    await doAction(
      () => (editing ? updateScheduledTask(editing.id, body) : createScheduledTask(body)),
      editing ? '定时任务已更新' : '定时任务已创建',
    );
    setOpen(false);
  };

  const applyTemplate = (tpl: (typeof CRON_TEMPLATES)[number]) => {
    form.setFieldsValue({ cron_expr: tpl.cron });
    if (tpl.task_type) form.setFieldsValue({ task_type: tpl.task_type });
  };

  const columns: ColumnsType<ScheduledTask> = [
    { title: '任务名称', dataIndex: 'name', key: 'name', width: 170 },
    {
      title: '类型', dataIndex: 'task_type_name', key: 'task_type', width: 110,
      render: (v: string, r) => (
        <Tag color={r.task_type === 'change_ip' ? 'purple' : r.task_type === 'power_on' ? 'green' : 'orange'}>{v}</Tag>
      ),
    },
    {
      title: '实例', dataIndex: 'instance_id', key: 'instance_id', width: 180, ellipsis: true,
      render: (v: string) => (
        <Tooltip title={v}>{instanceNameMap[v] ?? `${v.slice(0, 18)}…`}</Tooltip>
      ),
    },
    {
      title: 'Cron', dataIndex: 'cron_expr', key: 'cron_expr', width: 220,
      render: (v: string) => (
        <span>
          <code style={{ fontSize: 12 }}>{v}</code>
          <br />
          <span style={{ fontSize: 12, color: '#888' }}>{describeCron(v)}</span>
        </span>
      ),
    },
    {
      title: '下次执行', dataIndex: 'next_run_at', key: 'next_run_at', width: 170,
      render: (v: string | null) => fmtTime(v),
    },
    {
      title: '上次状态', dataIndex: 'last_status', key: 'last_status', width: 120,
      render: (v: string | null, r) =>
        v ? (
          <Tooltip title={r.last_error ?? r.last_run_at}>
            <Tag color={v === 'success' ? 'success' : 'error'}>{v === 'success' ? '成功' : '失败'}</Tag>
          </Tooltip>
        ) : (
          <span style={{ color: '#aaa' }}>-</span>
        ),
    },
    {
      title: '启用', dataIndex: 'enabled', key: 'enabled', width: 80,
      render: (v: boolean, r) => (
        <Switch
          checked={v}
          onChange={(checked) => doAction(() => toggleScheduledTask(r.id, checked), checked ? '已启用' : '已禁用')}
        />
      ),
    },
    {
      title: '操作', key: 'action', width: 200, fixed: 'right',
      render: (_, record) => (
        <Space>
          <Button
            type="link" size="small" icon={<PlayCircleOutlined />}
            onClick={() => doAction(() => runScheduledTaskNow(record.id), '已触发执行，请查看上次状态')}
          >
            立即执行
          </Button>
          <Button type="link" size="small" onClick={() => openEdit(record)}>编辑</Button>
          <Popconfirm title="确定删除该定时任务吗？" onConfirm={() => doAction(() => deleteScheduledTask(record.id), '已删除')}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title="定时任务"
      extra={
        <Space>
          <Button onClick={fetchAll}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建定时任务
          </Button>
        </Space>
      }
    >
      <Space style={{ marginBottom: 16 }}>
        <Input
          placeholder="搜索任务名称"
          prefix={<SearchOutlined />}
          allowClear
          style={{ width: 240 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <span style={{ color: '#888', fontSize: 12 }}>cron 按北京时间解析，每分钟扫描一次</span>
      </Space>
      <Table<ScheduledTask>
        rowKey="id"
        columns={columns}
        dataSource={filtered}
        loading={loading}
        scroll={{ x: 1400 }}
        pagination={{ showSizeChanger: true, showTotal: (t) => `共 ${t} 个任务` }}
      />
      <Modal
        title={editing ? '编辑定时任务' : '新建定时任务'}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        destroyOnClose
        width={600}
      >
        <Form<FormValues> form={form} layout="vertical" onFinish={onFinish} initialValues={{ enabled: true }}>
          <Form.Item name="name" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]}>
            <Input placeholder="如：开发机每晚关机" />
          </Form.Item>
          <Form.Item name="tenant_id" label="租户" rules={[{ required: true, message: '请选择租户' }]}>
            <Select
              placeholder="选择租户"
              options={tenants.map((t) => ({ label: `${t.name}（${t.region}）`, value: t.id }))}
            />
          </Form.Item>
          <Form.Item name="instance_id" label="实例" rules={[{ required: true, message: '请选择实例' }]}>
            <Select
              placeholder={tenantId ? '选择实例' : '请先选择租户'}
              loading={instLoading}
              disabled={!tenantId}
              showSearch
              optionFilterProp="label"
              options={instances.map((i) => ({ label: `${i.name}`, value: i.id }))}
            />
          </Form.Item>
          <Form.Item name="task_type" label="任务类型" rules={[{ required: true }]}>
            <Select
              options={(taskTypes.length ? taskTypes : [
                { value: 'power_on', label: '定时开机' },
                { value: 'power_off', label: '定时关机' },
                { value: 'reboot', label: '定时重启' },
                { value: 'change_ip', label: '定时换 IP' },
              ]).map((t) => ({ label: t.label, value: t.value }))}
            />
          </Form.Item>
          <Form.Item
            name="cron_expr"
            label="Cron 表达式"
            rules={[{ required: true, message: '请输入 cron 表达式' }]}
            extra={
              cronExpr ? (
                <span style={{ color: '#1677ff' }}>解析为：{describeCron(cronExpr)}（北京时间）</span>
              ) : (
                '标准 5 段：分 时 日 月 周，如 0 2 * * * 表示每天 2:00'
              )
            }
          >
            <Input placeholder="如：0 2 * * *" />
          </Form.Item>
          <Form.Item label="常用模板">
            <Space wrap>
              {CRON_TEMPLATES.map((tpl) => (
                <Button key={tpl.label} size="small" onClick={() => applyTemplate(tpl)}>
                  {tpl.label}
                </Button>
              ))}
            </Space>
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
