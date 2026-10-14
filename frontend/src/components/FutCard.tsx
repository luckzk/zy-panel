import type { CSSProperties, ReactNode } from 'react';
import { Card } from 'antd';
import { useThemeStore } from '../stores/theme';

interface FutCardProps {
  title?: ReactNode;
  extra?: ReactNode;
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
  bodyStyle?: CSSProperties;
}

/**
 * 未来主义卡片：1:1 复刻 v0 futuristic-dashboard 模板的 shadcn Card。
 * - 未来主义主题下：bg-slate-900/50 + border-slate-700/50 + backdrop-blur，
 *   头部带底部分隔线，标题亮字 + 青色图标。
 * - 其他主题下：降级为普通 AntD Card，API 保持一致。
 */
export default function FutCard({ title, extra, children, className, style, bodyStyle }: FutCardProps) {
  const futuristic = useThemeStore((s) => s.mode) === 'futuristic';

  if (!futuristic) {
    return (
      <Card title={title} extra={extra} className={className} style={style} styles={{ body: bodyStyle }}>
        {children}
      </Card>
    );
  }

  return (
    <div className={`fut-card${className ? ` ${className}` : ''}`} style={style}>
      {(title || extra) && (
        <div className="fut-card-head">
          <div className="fut-card-title">{title}</div>
          {extra && <div className="fut-card-extra">{extra}</div>}
        </div>
      )}
      <div className="fut-card-body" style={bodyStyle}>
        {children}
      </div>
    </div>
  );
}
