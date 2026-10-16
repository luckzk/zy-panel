import type { ReactElement } from 'react';
import { Navigate, createBrowserRouter, useLocation } from 'react-router-dom';
import { useAuthStore } from '../stores/auth';
import MainLayout from '../layouts/MainLayout';
import Login from '../pages/Login';
import Dashboard from '../pages/Dashboard';
import Tenants from '../pages/Tenants';
import Instances from '../pages/Instances';
import InstanceDetail from '../pages/InstanceDetail';
import SnatchTasks from '../pages/SnatchTasks';
import AliyunSpot from '../pages/AliyunSpot';
import AliyunImages from '../pages/AliyunImages';
import AliyunVpc from '../pages/AliyunVpc';
import AliyunOss from '../pages/AliyunOss';
import AliyunRds from '../pages/AliyunRds';
import AliyunMonitoring from '../pages/AliyunMonitoring';
import Network from '../pages/Network';
import Security from '../pages/Security';
import Volumes from '../pages/Volumes';
import Monitoring from '../pages/Monitoring';
import Dns from '../pages/Dns';
import System from '../pages/System';
import Notifications from '../pages/Notifications';
import ScheduledTasks from '../pages/ScheduledTasks';
import Billing from '../pages/Billing';
import FreeTier from '../pages/FreeTier';
import ObjectStorage from '../pages/ObjectStorage';
import Terminal from '../pages/Terminal';
import IAM from '../pages/IAM';
import Databases from '../pages/Databases';

/** 鉴权守卫：无 token 时跳转到登录页 */
function RequireAuth({ children }: { children: ReactElement }) {
  const token = useAuthStore((s) => s.token);
  const location = useLocation();
  if (!token) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return children;
}

/** 路由表 */
export const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  {
    path: '/',
    element: (
      <RequireAuth>
        <MainLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: 'dashboard', element: <Dashboard /> },
      { path: 'tenants', element: <Tenants /> },
      { path: 'instances', element: <Instances /> },
      { path: 'instances/:id', element: <InstanceDetail /> },
      { path: 'snatch-tasks', element: <SnatchTasks /> },
      { path: 'spot-instances', element: <AliyunSpot /> },
      { path: 'aliyun-images', element: <AliyunImages /> },
      { path: 'aliyun-vpc', element: <AliyunVpc /> },
      { path: 'aliyun-oss', element: <AliyunOss /> },
      { path: 'aliyun-rds', element: <AliyunRds /> },
      { path: 'aliyun-monitoring', element: <AliyunMonitoring /> },
      { path: 'network', element: <Network /> },
      { path: 'security', element: <Security /> },
      { path: 'volumes', element: <Volumes /> },
      { path: 'monitoring', element: <Monitoring /> },
      { path: 'dns', element: <Dns /> },
      { path: 'notifications', element: <Notifications /> },
      { path: 'scheduled-tasks', element: <ScheduledTasks /> },
      { path: 'billing', element: <Billing /> },
      { path: 'free-tier', element: <FreeTier /> },
      { path: 'object-storage', element: <ObjectStorage /> },
      { path: 'terminal', element: <Terminal /> },
      { path: 'iam', element: <IAM /> },
      { path: 'databases', element: <Databases /> },
      { path: 'system', element: <System /> },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);
