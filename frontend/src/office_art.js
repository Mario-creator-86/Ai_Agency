/** Pixel material library. Decorative finishes only; no operational state or network I/O. */
function pixel(ctx, x, y, w, h, color) {
  ctx.fillStyle = color;
  ctx.fillRect(Math.round(x), Math.round(y), Math.max(1, Math.round(w)), Math.max(1, Math.round(h)));
}

/** Layered ceramic and broad leaves, with a stable silhouette per existing prop seed. */
export function drawBotanical(ctx, x, y, seed) {
  const p = (dx, dy, w, h, color) => pixel(ctx, x + dx, y + dy, w, h, color);
  p(-10, -2, 21, 3, '#10251c60');
  p(-7, -12, 15, 10, '#a96e50');
  p(-5, -2, 11, 2, '#734632');
  p(-6, -10, 3, 7, '#dfa87b');
  p(5, -10, 2, 8, '#80513c');
  p(-8, -14, 17, 3, '#ecc29a');
  p(-6, -14, 13, 1, '#543d2d');
  p(-1, -37, 2, 23, '#64856a');
  const branches = [[-11,-35,10,5], [2,-31,11,5], [-10,-24,10,5], [2,-21,9,4], [-3,-42,6,8]];
  for (let i = 0; i < branches.length; i += 1) {
    const [lx, ly, w, h] = branches[i];
    const shift = ((seed >>> (i * 3)) & 3) - 1;
    p(lx, ly + shift, w, h, i % 2 ? '#548663' : '#6e9a6b');
    p(lx + 1, ly + shift, w - 2, 1, '#a6bc7e');
    p(lx + 1, ly + h + shift, w - 2, 1, '#325c47');
  }
}

/** Static material detailing of an existing room; never creates a purchased object. */
export function drawRoomMaterials(ctx, zone, accent) {
  const {x, y, width: w, height: h} = zone;
  const panelY = y + h - 39;
  pixel(ctx, x + 2, panelY, w - 4, 27, '#3a3b30');
  pixel(ctx, x + 2, panelY, w - 4, 1, '#a1946b');
  for (let bx = x + 10; bx < x + w - 5; bx += 24) {
    pixel(ctx, bx, panelY + 3, 1, 21, '#716c50');
    pixel(ctx, bx + 2, panelY + 3, 1, 21, '#282e26');
  }
  // Acoustic panels on the wall give large empty volumes a deliberate rhythm.
  if (w > 380 && h < 180) {
    for (let sx = x + w * 0.35; sx < x + w * 0.65; sx += 8) {
      pixel(ctx, sx, y + 28, 3, h - 72, '#e9d4a409');
    }
  }
  pixel(ctx, x + 8, y + 19, Math.min(82, w - 16), 1, accent);
}

export function drawFacadeMaterials(ctx, building) {
  const {x, y, width: w, height: h} = building;
  for (let cy = y + 4; cy < y + h - 8; cy += 18) {
    pixel(ctx, x - 12, cy, 10, 16, '#536158');
    pixel(ctx, x - 12, cy, 10, 1, '#7f8b77');
    pixel(ctx, x + w + 2, cy, 10, 16, '#3c5147');
    pixel(ctx, x + w + 2, cy, 10, 1, '#677b68');
  }
  pixel(ctx, x - 3, y, 2, h, '#c0a56b');
  pixel(ctx, x + w + 1, y, 1, h, '#977e50');
}
