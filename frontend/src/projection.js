/** Full snapshots are authoritative; duplicate and older responses cannot rewind the UI. */
export function acceptSnapshot(current, incoming) {
  if (incoming.schema_version !== 1 || !Number.isSafeInteger(incoming.cursor)) {
    throw new Error('Incompatible data version. Reload the application.');
  }
  if (current && incoming.cursor < current.cursor) return current;
  return incoming;
}

