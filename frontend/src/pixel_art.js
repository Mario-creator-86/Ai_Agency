// Integer raster primitives: every outline, joint and colour cluster stays on the pixel grid.
const sprites = new Map();
export function shade(color, amount) {
  const n = parseInt(color.slice(1), 16);
  const channel = shift => Math.max(0, Math.min(255, ((n >> shift) & 255) + amount)).toString(16).padStart(2, '0');
  return '#' + channel(16) + channel(8) + channel(0);
}
export function pixelPen(ctx) {
  const rect = (x, y, w, h, color) => {
    ctx.fillStyle = color; ctx.fillRect(Math.round(x), Math.round(y), Math.max(1, Math.round(w)), Math.max(1, Math.round(h)));
  };
  const line = (x0, y0, x1, y1, color, width = 1) => {
    x0 = Math.round(x0); y0 = Math.round(y0); x1 = Math.round(x1); y1 = Math.round(y1);
    const dx = Math.abs(x1 - x0), sx = x0 < x1 ? 1 : -1, dy = -Math.abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
    let error = dx + dy;
    for (;;) {
      rect(x0 - Math.floor(width / 2), y0 - Math.floor(width / 2), width, width, color);
      if (x0 === x1 && y0 === y1) break;
      const twice = 2 * error;
      if (twice >= dy) { error += dy; x0 += sx; }
      if (twice <= dx) { error += dx; y0 += sy; }
    }
  };
  const ellipse = (cx, cy, rx, ry, color, ring = 0) => {
    for (let y = -ry; y <= ry; y++) for (let x = -rx; x <= rx; x++) {
      if ((x * x) / (rx * rx) + (y * y) / (ry * ry) > 1) continue;
      if (ring && rx > ring && ry > ring && (x * x) / ((rx - ring) ** 2) + (y * y) / ((ry - ring) ** 2) < 1) continue;
      rect(cx + x, cy + y, 1, 1, color);
    }
  };
  const polygon = (points, color) => {
    const bottom = Math.ceil(Math.max(...points.map(p => p[1])));
    for (let y = Math.floor(Math.min(...points.map(p => p[1]))); y <= bottom; y++) {
      const crossings = [];
      for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
        const a = points[j], b = points[i], scan = y + 0.5;
        if ((a[1] <= scan && b[1] > scan) || (b[1] <= scan && a[1] > scan)) crossings.push(a[0] + (scan - a[1]) * (b[0] - a[0]) / (b[1] - a[1]));
      }
      crossings.sort((a, b) => a - b);
      for (let i = 0; i + 1 < crossings.length; i += 2) {
        const start = Math.ceil(crossings[i]), end = Math.floor(crossings[i + 1]);
        if (end >= start) rect(start, y, end - start + 1, 1, color);
      }
    }
  };
  return { rect, line, ellipse, polygon };
}

/** A bounded atlas of authored frames. Direction mirrors the finished silhouette, not its path. */
export function blitActor(ctx, key, bounds, x, y, direction, paint) {
  let sprite = sprites.get(key);
  if (!sprite && typeof document !== 'undefined') {
    sprite = document.createElement('canvas'); sprite.width = bounds.width; sprite.height = bounds.height;
    const c = sprite.getContext('2d'); c.translate(bounds.ox, bounds.oy); paint(c);
    if (sprites.size >= 256) sprites.delete(sprites.keys().next().value);
    sprites.set(key, sprite);
  }
  ctx.save(); ctx.translate(Math.round(x), Math.round(y)); ctx.scale(direction, 1);
  ctx.imageSmoothingEnabled = false;
  if (sprite) ctx.drawImage(sprite, -bounds.ox, -bounds.oy); else paint(ctx);
  ctx.restore();
}
