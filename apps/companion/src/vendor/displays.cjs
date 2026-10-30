/**
 * Adapted from PC2005-cloud/dsh-pet src/shared/displays.ts.
 * Upstream commit 34cf7ec4dd1ca99a9a9ac5bcb4571d887862e226.
 * Copyright (c) 2026 PC2005-cloud. MIT; see dsh-pet-LICENSE.txt.
 * Change: removed TypeScript annotations and unused diagnostics/rebasing.
 */
'use strict';
/** 矩形右缘（不含）。 */
const rectRight = (r) => r.x + r.width;
/** 矩形下缘（不含）。 */
const rectBottom = (r) => r.y + r.height;

/** 外接矩形：视口原点与比例换算仍取它，但边界判定一律走并集；空列表返回 0×0。 */
const boundingRect = (rects) => {
  if (rects.length === 0) return { x: 0, y: 0, width: 0, height: 0 };
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const r of rects) {
    x0 = Math.min(x0, r.x);
    y0 = Math.min(y0, r.y);
    x1 = Math.max(x1, rectRight(r));
    y1 = Math.max(y1, rectBottom(r));
  }
  return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
};

/** 点是否落在矩形内（右/下缘不含）：相邻两屏缝隙为 0 时，点归左/上那块。 */
const pointInRect = (r, x, y) =>
  x >= r.x && x < rectRight(r) && y >= r.y && y < rectBottom(r);

/** 点被哪块屏覆盖；无则 null。重叠时取列表中第一块（与 Chromium「先发现者优先」一致）。 */
const rectAtPoint = (rects, x, y) => {
  for (const r of rects) if (pointInRect(r, x, y)) return r;
  return null;
};

/** 同 rectAtPoint，返回下标（−1 = 无覆盖）；抛掷要用下标记住当前所在屏。 */
const indexAtPoint = (rects, x, y) => {
  for (let i = 0; i < rects.length; i++) if (pointInRect(rects[i], x, y)) return i;
  return -1;
};

/** 点到矩形的最短距离平方（点在矩形内为 0）。 */
const distToRectSq = (r, x, y) => {
  const dx = Math.max(r.x - x, 0, x - rectRight(r));
  const dy = Math.max(r.y - y, 0, y - rectBottom(r));
  return dx * dx + dy * dy;
};

/** 离点最近的屏下标；空列表返回 −1。用于宠物落在空洞或屏幕被拔掉后归位。 */
const nearestIndex = (rects, x, y) => {
  let best = -1;
  let bestD = Infinity;
  for (let i = 0; i < rects.length; i++) {
    const d = distToRectSq(rects[i], x, y);
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return best;
};

/** 点所在屏；不在任何屏上时取最近的那块（列表为空才返回 null）。 */
const resolveRect = (rects, x, y) => {
  const hit = rectAtPoint(rects, x, y);
  if (hit) return hit;
  const i = nearestIndex(rects, x, y);
  return i < 0 ? null : rects[i];
};

/** 把点夹进指定矩形（右/下缘留 1px，保证结果仍满足 pointInRect）。 */
const clampPointInRect = (r, x, y) => ({
  x: Math.min(Math.max(x, r.x), rectRight(r) - 1),
  y: Math.min(Math.max(y, r.y), rectBottom(r) - 1),
});

/** 把点夹进并集：已在并集内原样返回，否则夹进最近的那块屏。用于显示器拔插后把落在空洞里的宠物拉回可见区。 */
const clampPointToRegion = (rects, x, y) => {
  if (rectAtPoint(rects, x, y)) return { x, y };
  const i = nearestIndex(rects, x, y);
  return i < 0 ? { x, y } : clampPointInRect(rects[i], x, y);
};


module.exports = { resolveRect, clampPointToRegion, rectAtPoint, nearestIndex };
