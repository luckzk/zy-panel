import { type CSSProperties, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'framer-motion';

/** 页面切换上浮：配合 MainLayout 的 AnimatePresence，按路由 key 触发 */
export function PageTransition({ children, routeKey }: { children: ReactNode; routeKey: string }) {
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={routeKey}
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.25, ease: 'easeOut' }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

/** 依次出现容器：子项间隔 0.06s 依次上浮 */
export function StaggerGroup({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <motion.div
      style={style}
      initial="hidden"
      animate="show"
      variants={{ hidden: {}, show: { transition: { staggerChildren: 0.06 } } }}
    >
      {children}
    </motion.div>
  );
}

/** 依次出现子项：与 PageTransition 同款上浮 */
export function StaggerItem({ children }: { children: ReactNode }) {
  return (
    <motion.div
      variants={{
        hidden: { opacity: 0, y: 16 },
        show: { opacity: 1, y: 0, transition: { duration: 0.25, ease: 'easeOut' } },
      }}
    >
      {children}
    </motion.div>
  );
}
