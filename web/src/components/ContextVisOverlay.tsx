/**
 * ContextVisOverlay —— ContextVis 的挂载壳（host-specific glue）。
 *
 * 把 ContextVis 浮在中间终端对话区的右上角，而非挤在右侧固定窄栏里——宽度由
 * 我们掌控，treemap 更大更清楚；右侧栏腾给后续功能。订阅本聊天标签的事件通道
 * 产出快照，喂给纯渲染的 {@link ContextVisPanel}。
 *
 * 定位（与用户敲定）：平时用户只管对话、不必关心 context；当 agent 开始出错或
 * 窗口将满时，才需要可视化并（未来）交互编辑。开发阶段先默认展开、不透明，便于
 * 即时观察；美观/默认折叠/半透明等留待功能完备后再调。
 *
 * v1：固定右上角 + 可折叠（折叠成药丸）。拖动/缩放留待以后；这里也是未来
 * 交互式压缩（选中 chunk → drop/keep/合并 → 预览）的天然宿主。
 */

import { useState } from "react";

import { ContextVisPanel } from "@/components/ContextVisPanel";
import { useContextSnapshot } from "@/lib/contextvis/adapter";
import { cn } from "@/lib/utils";

function toneClasses(percent: number): { bar: string; text: string } {
  if (percent >= 90) return { bar: "bg-destructive", text: "text-destructive" };
  if (percent >= 70) return { bar: "bg-warning", text: "text-warning" };
  return { bar: "bg-success", text: "text-success" };
}

export function ContextVisOverlay({ channel }: { channel: string }) {
  const snapshot = useContextSnapshot(channel);
  const [collapsed, setCollapsed] = useState(false);

  // 没有真实窗口（尚未开始对话）时不挂任何东西，保持终端干净。
  if (snapshot.budget <= 0) return null;

  const pct = snapshot.percent;
  const tone = toneClasses(pct);

  return (
    <div className="absolute right-2 top-2 z-10 w-[440px] max-w-[calc(100%-1rem)]">
      {collapsed ? (
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          aria-label="expand context panel"
          className={cn(
            "flex items-center gap-2 rounded-lg px-3 py-1.5 shadow-xl",
            "border border-current/20 bg-background-base/95 backdrop-blur-sm",
          )}
        >
          <span className="text-display text-xs tracking-wider text-text-tertiary">
            context
          </span>
          <span className="h-1.5 w-12 overflow-hidden rounded-full bg-current/15">
            <span
              className={cn("block h-full rounded-full", tone.bar)}
              style={{ width: `${Math.max(4, Math.min(100, pct))}%` }}
            />
          </span>
          <span className={cn("text-xs font-medium tabular-nums", tone.text)}>{pct}%</span>
          {snapshot.compactions.length > 0 && (
            <span className="text-xs text-text-tertiary">
              ×{snapshot.compactions.length}
            </span>
          )}
        </button>
      ) : (
        <div className="max-h-[calc(100%-0.5rem)] overflow-y-auto rounded-lg shadow-xl">
          <ContextVisPanel snapshot={snapshot} onCollapse={() => setCollapsed(true)} />
        </div>
      )}
    </div>
  );
}
