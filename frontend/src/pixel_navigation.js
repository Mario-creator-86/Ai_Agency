/** Scene offsets in CSS pixels; clamp each axis independently to the visible artwork. */
export function sceneFrame({ width, height, worldWidth, worldHeight, zoom, panX = 0, panY = 0 }) {
  const scale = Math.max(0.01, Math.min(width / worldWidth, height / worldHeight)) * zoom;
  const limitX = Math.max(0, (worldWidth * scale - width) / 2);
  const limitY = Math.max(0, (worldHeight * scale - height) / 2);
  return { scale, panX: limitX ? Math.max(-limitX, Math.min(limitX, panX)) : 0, panY: limitY ? Math.max(-limitY, Math.min(limitY, panY)) : 0,
    limitX, limitY, movable: limitX > 0 || limitY > 0 };
}
