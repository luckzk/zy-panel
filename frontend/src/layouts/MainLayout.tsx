import { useMemo, useState } from 'react';
import { Avatar, Breadcrumb, Button, Dropdown, Layout, Menu, Segmented } from 'antd';
import type { MenuProps } from 'antd';
import {
  ApiOutlined,
  BellOutlined,
  BulbOutlined,
  CalendarOutlined,
  CloudServerOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  DollarOutlined,
  FolderOpenOutlined,
  GiftOutlined,
  GlobalOutlined,
  LineChartOutlined,
  LogoutOutlined,
  SafetyOutlined,
  SettingOutlined,
  CodeOutlined,
  ThunderboltOutlined,
  TeamOutlined,
  TableOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../stores/auth';
import { useThemeStore } from '../stores/theme';

const { Header, Sider, Content } = Layout;

/** 侧边栏菜单配置 */
const MENU_ITEMS: { key: string; label: string; icon: React.ReactNode }[] = [
  { key: '/dashboard', label: '总览', icon: <DashboardOutlined /> },
  { key: '/tenants', label: '租户配置', icon: <UserOutlined /> },
  { key: '/iam', label: 'IAM 用户', icon: <TeamOutlined /> },
  { key: '/instances', label: '实例管理', icon: <CloudServerOutlined /> },
  { key: '/snatch-tasks', label: '抢机任务', icon: <ThunderboltOutlined /> },
  { key: '/spot-instances', label: '抢占式实例', icon: <ThunderboltOutlined /> },
  { key: '/aliyun-images', label: '镜像管理', icon: <DatabaseOutlined /> },
  { key: '/scheduled-tasks', label: '定时任务', icon: <CalendarOutlined /> },
  { key: '/network', label: '网络 / 换 IP', icon: <GlobalOutlined /> },
  { key: '/security', label: '安全组', icon: <SafetyOutlined /> },
  { key: '/volumes', label: '卷管理', icon: <DatabaseOutlined /> },
  { key: '/databases', label: '数据库', icon: <TableOutlined /> },
  { key: '/object-storage', label: '对象存储', icon: <FolderOpenOutlined /> },
  { key: '/monitoring', label: '流量监控', icon: <LineChartOutlined /> },
  { key: '/billing', label: '费用分析', icon: <DollarOutlined /> },
  { key: '/free-tier', label: '免费额度', icon: <GiftOutlined /> },
  { key: '/dns', label: 'DNS 解析', icon: <ApiOutlined /> },
  { key: '/notifications', label: '通知渠道', icon: <BellOutlined /> },
  { key: '/terminal', label: 'Web 终端', icon: <CodeOutlined /> },
  { key: '/system', label: '系统设置', icon: <SettingOutlined /> },
];

/** 面包屑文案映射 */
const CRUMB_MAP: Record<string, string> = {
  dashboard: '总览',
  tenants: '租户配置',
  instances: '实例管理',
  'snatch-tasks': '抢机任务',
  'spot-instances': '抢占式实例',
  'aliyun-images': '镜像管理',
  'scheduled-tasks': '定时任务',
  network: '网络 / 换 IP',
  security: '安全组',
  volumes: '卷管理',
  'object-storage': '对象存储',
  monitoring: '流量监控',
  billing: '费用分析',
  'free-tier': '免费额度',
  dns: 'DNS 解析',
  notifications: '通知渠道',
  terminal: 'Web 终端',
  iam: 'IAM 用户',
  databases: '数据库',
  system: '系统设置',
};

/** 主布局：侧边栏菜单 + 顶栏面包屑/主题切换/用户信息 + 内容区 */
export default function MainLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();
  const { mode, setMode, dark } = useThemeStore();

  const selectedKey = useMemo(() => {
    const hit = MENU_ITEMS.find((m) => location.pathname.startsWith(m.key));
    return hit ? [hit.key] : [];
  }, [location.pathname]);

  const crumbs = useMemo(
    () =>
      location.pathname
        .split('/')
        .filter(Boolean)
        .map((p) => CRUMB_MAP[p] ?? p),
    [location.pathname],
  );

  const menuItems: MenuProps['items'] = MENU_ITEMS.map((m) => ({
    key: m.key,
    icon: m.icon,
    label: <Link to={m.key}>{m.label}</Link>,
  }));

  const userMenu: MenuProps = {
    items: [
      {
        key: 'logout',
        icon: <LogoutOutlined />,
        label: '退出登录',
        onClick: () => {
          logout();
          navigate('/login', { replace: true });
        },
      },
    ],
  };

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} theme={dark ? 'dark' : 'light'}>
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 700,
            fontSize: collapsed ? 18 : 16,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
          }}
        >
          {collapsed ? (
            <img src="favicon.svg" alt="zy" style={{ width: 28, height: 28 }} />
          ) : (
            <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <img src="favicon.svg" alt="zy-panel" style={{ width: 26, height: 26 }} />
              zy-panel
            </span>
          )}
        </div>
        <Menu mode="inline" selectedKeys={selectedKey} items={menuItems} theme={dark ? 'dark' : 'light'} />
      </Sider>
      <Layout>
        <Header
          style={{
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: mode === 'futuristic' ? undefined : dark ? '#141414' : '#fff',
            borderBottom:
              mode === 'futuristic' ? undefined : dark ? '1px solid #303030' : '1px solid #f0f0f0',
          }}
        >
          <Breadcrumb items={crumbs.map((c) => ({ title: c }))} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            {/* 主题切换：浅色 / 深色 / 未来主义 */}
            <Segmented
              size="small"
              value={mode}
              onChange={(v) => setMode(v as 'light' | 'dark' | 'futuristic')}
              options={[
                { value: 'light', label: '浅色' },
                { value: 'dark', label: '深色' },
                { value: 'futuristic', label: '未来' },
              ]}
            />
            <Button type="text" icon={<BulbOutlined />} size="small">
              v0.1.0
            </Button>
            <Dropdown menu={userMenu} placement="bottomRight">
              <span style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}>
                <Avatar size="small" icon={<UserOutlined />} />
                {user?.username ?? '管理员'}
              </span>
            </Dropdown>
          </div>
        </Header>
        <Content style={{ margin: 24, minHeight: 280 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
