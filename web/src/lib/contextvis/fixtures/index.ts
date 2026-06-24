/**
 * ContextVis fixture 源（dev-only）—— 录制 / 重放冻结的 context 状态。
 *
 * 动机：v2 的视图/交互（add / invalidate / promote、轮盘、画布）大半是**前端**活，
 * 但每次测试都新开 session、按序敲 prompt 既费时又费 token，且 LLM 有随机性。
 * fixture 把一次真实状态**冻结成 JSON**，之后无限次零-token、完全确定地重放。
 *
 * 冻结的是渲染层的**两个数据源**（这是关键）：
 *   ① 占用 + chunks —— {@link ContextSnapshot}（来自 useContextSnapshot 的 WS feed）
 *   ② 着色 + 引用图 + 产物/关键词 —— {@link RegimeColors}（来自 fetchRegimeColors 的 RPC）
 * 二者都冻结，连**检测器的判定**（主线 / focus / 引用图）都钉死 —— 这正是 session.branch
 * 给不了的：fork 会让 context.regime_colors 重跑 aux LLM、每次主线/弧都抖。**幂等来自这里。**
 *
 * 三层隔离的守约：注入点只在**适配器边界**（useContextSnapshot / fetchRegimeColors），
 * 渲染组件一行不知道 fixture 的存在。
 *
 * 用法：
 *   1. 录制：dev 模式下在 ContextVis 面板点「⬇ fixture」→ 下载 `<name>.json`
 *      → 放进本目录 `web/src/lib/contextvis/fixtures/`。
 *   2. 重放：访问 `/chat?fixture=<name>` → 面板每次刷新都是那个冻结状态、零 token。
 */

import type { RegimeColors } from "@/lib/contextvis/apply";
import type { ContextSnapshot } from "@/lib/contextvis/types";

/** 一份 fixture = 渲染层两个数据源的冻结快照 + 元信息。 */
export interface ContextVisFixture {
  /** slug（= 文件名去扩展名 = `?fixture=` 的值）。 */
  name: string;
  /** 录制时间戳（ms）。 */
  capturedAt: number;
  /** 可选：这个 case 想展示什么（剃刀缺口 / 目标操作）。 */
  note?: string;
  /** 数据源①：占用 + chunks。 */
  snapshot: ContextSnapshot;
  /** 数据源②：着色 + 引用图 + 产物/关键词（fetchRegimeColors 的原始返回）。 */
  regimeColors: RegimeColors;
}

// Vite 在构建时把本目录所有 *.json 内联（eager）。空目录 → {}，不报错。
const modules = import.meta.glob("./*.json", { eager: true }) as Record<
  string,
  { default: ContextVisFixture }
>;

/** 当前 URL 请求的 fixture 名（`?fixture=foo`），无则 null。 */
function fixtureName(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("fixture");
}

let _warned = false;

/**
 * 解析当前 `?fixture=` 指向的 fixture。未带参数 → null（= 真实模式，走 WS/RPC）。
 * 带了但找不到 → 一次性 warn + null（退化为真实模式，不打断）。
 */
export function activeFixture(): ContextVisFixture | null {
  const name = fixtureName();
  if (!name) return null;
  const mod = modules[`./${name}.json`];
  if (!mod) {
    if (!_warned) {
      _warned = true;
      console.warn(
        `[contextvis] fixture "${name}" 不存在。可用：`,
        availableFixtures(),
      );
    }
    return null;
  }
  return mod.default;
}

/** 是否处于 fixture 重放模式（任一取数点据此短路）。 */
export function fixtureActive(): boolean {
  return activeFixture() != null;
}

/** 本目录已收录的全部 fixture slug（dev 工具 / 报错提示用）。 */
export function availableFixtures(): string[] {
  return Object.keys(modules).map((p) => p.replace(/^\.\/|\.json$/g, ""));
}

const EMPTY_REGIME_COLORS: RegimeColors = {
  regime: "",
  focus: "",
  engine: "",
  reason: "",
  chunk_topics: {},
  reference_graph: {
    edges: [],
    artifacts: [],
    files: [],
    keywords: [],
    layers: [],
  },
};

/**
 * 录制器：把此刻的两个数据源打包成 fixture 并触发浏览器下载。
 * `regimeColors` 抓取失败时降级为空着色（仍可录占用 / 画布版图）。
 * 下载的 JSON 放进本目录即可被 glob 收录、`?fixture=<name>` 重放。
 */
export function downloadFixture(
  name: string,
  snapshot: ContextSnapshot,
  regimeColors: RegimeColors | null,
  note?: string,
): void {
  const fixture: ContextVisFixture = {
    name,
    capturedAt: Date.now(),
    ...(note ? { note } : {}),
    snapshot,
    regimeColors: regimeColors ?? EMPTY_REGIME_COLORS,
  };
  const blob = new Blob([JSON.stringify(fixture, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${name}.json`;
  a.click();
  URL.revokeObjectURL(url);
}
