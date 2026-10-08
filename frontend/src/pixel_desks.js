import PIXEL_LAYOUT from '../../config/pixel_office.json' with { type: 'json' };
export { PIXEL_LAYOUT };

/** Backend pixel_slot is a reserved personal seat; array order and state changes cannot move it. */
export function staffPositions(agents, layout = PIXEL_LAYOUT) {
  const stations = layout.stations;
  const used = new Set();
  let extra = stations.length;
  return [...agents].sort((a, b) => String(a.id || a.agent_id).localeCompare(String(b.id || b.agent_id))).map(agent => {
    const id = String(agent.id || agent.agent_id);
    const known = stations.findIndex(s => s.desk_id === agent.desk_id);
    let slot = Number.isSafeInteger(agent.pixel_slot) && agent.pixel_slot >= 0 ? agent.pixel_slot : known;
    if (slot < 0 || used.has(slot)) { while (used.has(extra)) extra++; slot = extra++; }
    used.add(slot);
    const station = stations[slot % stations.length];
    return { ...station, agent, id, slot, page: Math.floor(slot / stations.length), deskId: agent.pixel_desk_id || `pixel_desk_${id}`, x: station.x, y: station.y, row: station.row };
  });
}

/** Reuse the approved illustration for chair/foreground occlusion, without repainting furniture. */
export function restoreFurniture(ctx, image, person, layout = PIXEL_LAYOUT) {
  if (!image.complete || !image.naturalWidth) return;
  const sx = image.naturalWidth / layout.world.width;
  const sy = image.naturalHeight / layout.world.height;
  for (const box of person.foreground || []) {
    // Leave the head visible above the chair; restore the illustrated backrest below the neck.
    const top = Math.max(box.y, person.y - 26 * (person.scale || 1.5));
    const height = box.y + box.height - top;
    if (height <= 0) continue;
    ctx.drawImage(image, box.x * sx, top * sy, box.width * sx, height * sy, box.x, top, box.width, height);
  }
}
