import axios from 'axios';
import { message } from 'antd';
import { create } from 'zustand';
import { api, clearToken, setToken } from '../api/client';

/** 登录用户信息 */
export interface UserInfo {
  username: string;
}

interface AuthState {
  token: string | null;
  user: UserInfo | null;
  /** 登录：调 POST /api/v1/auth/login；失败时直接抛出，由调用方提示 */
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const USER_KEY = 'oci_panel_user';

/** 安全读取本地用户信息 */
function loadUser(): UserInfo | null {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) ?? 'null') as UserInfo | null;
  } catch {
    return null;
  }
}

export const useAuthStore = create<AuthState>()((set) => ({
  token: localStorage.getItem('oci_panel_token'),
  user: loadUser(),

  login: async (username: string, password: string) => {
    try {
      const resp = await api.post<{ token: string; user: UserInfo }>('/api/v1/auth/login', {
        username,
        password,
      });
      const { token, user } = resp.data;
      setToken(token);
      localStorage.setItem(USER_KEY, JSON.stringify(user));
      set({ token, user });
      message.success(`欢迎回来，${user.username}`);
    } catch (e) {
      // 完全连不上后端（无 response）：明确报错，不再静默进入演示模式
      if (axios.isAxiosError(e) && !e.response) {
        message.error('无法连接后端服务，请检查后端是否已启动');
      }
      throw e;
    }
  },

  logout: () => {
    clearToken();
    localStorage.removeItem(USER_KEY);
    set({ token: null, user: null });
  },
}));
