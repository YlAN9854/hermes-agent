/**
 * Squarified treemap 布局（Bruls/Huizing/van Wijk）。
 *
 * 给一个矩形和一组带权值的项，产出每项的子矩形，面积 ∝ 权值、长宽比尽量接近
 * 1（方块状，便于阅读标签）。纯函数，无依赖——ContextVis 用它在每个类型带内
 * 把 chunk 铺成"量级编码面积"的格子。
 */

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface TreemapCell<T> extends Rect {
  item: T;
}

interface Scaled<T> {
  area: number;
  data: T;
}

/** 一行的最差长宽比（越小越方）。 */
function worstRatio<T>(row: Scaled<T>[], side: number): number {
  if (row.length === 0 || side <= 0) return Infinity;
  const sum = row.reduce((s, r) => s + r.area, 0);
  const max = Math.max(...row.map((r) => r.area));
  const min = Math.min(...row.map((r) => r.area));
  if (sum <= 0 || min <= 0) return Infinity;
  const s2 = sum * sum;
  return Math.max((side * side * max) / s2, s2 / (side * side * min));
}

export function squarify<T>(
  items: { value: number; data: T }[],
  rect: Rect,
): TreemapCell<T>[] {
  const cells: TreemapCell<T>[] = [];
  const positive = items.filter((i) => i.value > 0);
  const total = positive.reduce((s, i) => s + i.value, 0);
  if (total <= 0 || rect.w <= 0 || rect.h <= 0) return cells;

  const area = rect.w * rect.h;
  const remaining: Scaled<T>[] = positive.map((i) => ({
    area: (i.value / total) * area,
    data: i.data,
  }));

  let { x, y, w, h } = rect;

  const layoutRow = (row: Scaled<T>[]) => {
    const horizontal = w >= h; // 沿较短边铺这一行
    const side = horizontal ? h : w;
    const sum = row.reduce((s, r) => s + r.area, 0);
    const thickness = side > 0 ? sum / side : 0;
    let offset = 0;
    for (const r of row) {
      const length = thickness > 0 ? r.area / thickness : 0;
      if (horizontal) {
        cells.push({ x, y: y + offset, w: thickness, h: length, item: r.data });
      } else {
        cells.push({ x: x + offset, y, w: length, h: thickness, item: r.data });
      }
      offset += length;
    }
    if (horizontal) {
      x += thickness;
      w -= thickness;
    } else {
      y += thickness;
      h -= thickness;
    }
  };

  let row: Scaled<T>[] = [];
  while (remaining.length) {
    const side = w >= h ? h : w;
    const next = remaining[0];
    if (row.length === 0 || worstRatio([...row, next], side) <= worstRatio(row, side)) {
      row.push(next);
      remaining.shift();
    } else {
      layoutRow(row);
      row = [];
    }
  }
  if (row.length) layoutRow(row);
  return cells;
}
