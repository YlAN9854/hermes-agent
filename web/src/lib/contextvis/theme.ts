/**
 * ContextVis 视觉令牌 —— **浅色 Swiss 科学仪器**皮肤的单一真相源(SVG 硬编码色)。
 *
 * 与宿主 Hermes DS 解耦:ContextVis 容器套 `.cv-scope`(见 `src/index.css`)把 DS 令牌翻成
 * **白底 + 深墨 + JetBrains Mono**;DS 类(text-text-* 、border、card 等)随之自动浅色。但
 * treemap、弧、命运沟这些**画在 SVG 里的颜色无法走 CSS 令牌**,故集中在此——鲜明 categorical、可读、
 * 含义对齐。改色只动这一处(三处组件都 import),守 CLAUDE.md「类型恒定可辨 / 量级编码」。
 */

/** 5 类 chunk 的 categorical 色(鲜明、白底高分离、含义对齐)。 */
export const CV_TYPE_FILL: Record<string, string> = {
  system: "#5B5BD6", // indigo —— 系统底座(冷、根基)
  tool_schema: "#0E9488", // teal —— 工具表(结构)
  history: "#3B6FB5", // steel blue —— 对话(中性冷)
  file: "#2E9E5B", // green —— 文件(内容 / 膨胀主因)
  tool_result: "#D9822B", // amber —— 工具结果(暖、产出)
};

/** 类型 → 中文标签(三处组件共用)。 */
export const CV_TYPE_LABEL: Record<string, string> = {
  system: "系统",
  tool_schema: "工具表",
  history: "对话",
  file: "文件",
  tool_result: "工具结果",
};

/** treemap「类型带」顺序 + 色(自顶向下;ContextVisPanel 的 BANDS）。 */
export const CV_BANDS: { type: keyof typeof CV_TYPE_FILL | string; color: string }[] = [
  { type: "system", color: CV_TYPE_FILL.system },
  { type: "tool_schema", color: CV_TYPE_FILL.tool_schema },
  { type: "history", color: CV_TYPE_FILL.history },
  { type: "file", color: CV_TYPE_FILL.file },
  { type: "tool_result", color: CV_TYPE_FILL.tool_result },
];

/** 主题着色(逐轮 topic / 线程)—— 8 色 qualitative,白底上互相可分。 */
export const CV_TOPIC_PALETTE = [
  "#E0701A", "#0E9488", "#5B5BD6", "#C2497A",
  "#2E9E5B", "#2563C9", "#A88410", "#8B4FC9",
];

/** 命运色(白底校准:keep 绿 / fold 琥珀 / drop 红)。 */
export const CV_FATE = {
  keep: "#1F9D57",
  fold: "#C77D17",
  drop: "#E5484D",
} as const;

/** 引用弧 / 关键词追踪色。 */
export const CV_ARC = {
  downstream: "#E5397A", // 下游(谁依赖我 / 爆炸半径)
  upstream: "#1E88E5", // 上游(我依赖谁 / provenance)
  trace: "#9333EA", // 关键词贯穿路径(violet)
};

/** 画布面 / 墨(白底 Swiss;SVG 里用,不走 currentColor 的地方)。 */
export const CV_SURFACE = {
  ink: "#1A2230", // 主墨(标签 / 选中描边)
  inkSoft: "rgba(26,34,48,0.62)", // 次级墨
  canvas: "#FFFFFF", // 画布白
  rowBase: "#ECE9FB", // 系统底座行(淡 indigo)
  rowTurn: "#F4F6FA", // 对话轮行底(极浅灰蓝)
  rowFold: "#E4E8EF", // 折叠行(浅灰)
  hair: "rgba(26,34,48,0.12)", // 发丝线 / 弱边
  cellStroke: "rgba(26,34,48,0.16)", // 子格描边
};
