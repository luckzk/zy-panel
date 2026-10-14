import axios, { AxiosError } from 'axios';
import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { message } from 'antd';

/** 后端统一响应体：{ code, msg, data }，code 为 0 表示成功 */
export interface ApiResponse<T> {
  code: number;
  msg: string;
  data: T;
}

const TOKEN_KEY = 'oci_panel_token';

/** token 统一走 localStorage，避免 store 与 client 循环引用 */
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

/** axios 实例：baseURL 优先读环境变量 VITE_API_BASE，默认同源相对路径。
 *  生产经 nginx /api/v1/ 反代到后端，开发经 vite proxy，均无需写死主机地址。
 *  写死 http://localhost:8818 会导致用服务器 IP 访问时浏览器去连本机，登录失败。 */
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE ?? '',
  timeout: 30000,
});

/** 请求拦截器：自动附加 Authorization: Bearer <token> */
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getToken();
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`);
  }
  return config;
});

/** 响应拦截器：解包 {code,msg,data}；401 跳登录 */
api.interceptors.response.use(
  (resp: AxiosResponse) => {
    const payload = resp.data as ApiResponse<unknown>;
    if (payload && typeof payload.code === 'number' && payload.code !== 0) {
      message.error(payload.msg || '请求失败');
      return Promise.reject(new Error(payload.msg || '请求失败'));
    }
    // 解包：调用方拿到的 resp.data 直接就是业务数据
    if (payload && typeof payload.code === 'number') {
      resp.data = payload.data;
    }
    return resp;
  },
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      clearToken();
      message.error('登录已过期，请重新登录');
      window.location.href = '/login';
    } else if (error.response) {
      const data = error.response.data as { msg?: string } | undefined;
      message.error(data?.msg || `请求失败（${error.response.status}）`);
    }
    // 无 response 表示网络错误，交给调用方处理（登录页会兜底演示模式）
    return Promise.reject(error);
  },
);
