import { File, Paths } from 'expo-file-system';
import { logHike } from './api';

// a hike that finished but couldn't be saved to the backend yet -- the
// expected case is finishing a hike while still out of cell range, which
// this whole app is specifically built to make possible. Queued locally
// and retried automatically rather than just losing the hike.
export type PendingHike = {
  id: string;
  distanceM: number;
  movingTimeS: number;
  osmId: number | null;
  queuedAt: string;
};

const file = new File(Paths.document, 'pending-hikes.json');

function readAll(): PendingHike[] {
  if (!file.exists) return [];
  try {
    return JSON.parse(file.textSync()) as PendingHike[];
  } catch {
    // a corrupted queue file shouldn't crash every caller that touches
    // it -- treat it as an empty queue rather than throwing
    return [];
  }
}

function writeAll(hikes: PendingHike[]): void {
  file.write(JSON.stringify(hikes));
}

export function listPendingHikes(): PendingHike[] {
  return readAll();
}

export function enqueuePendingHike(distanceM: number, movingTimeS: number, osmId: number | null): void {
  const hikes = readAll();
  hikes.push({
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    distanceM,
    movingTimeS,
    osmId,
    queuedAt: new Date().toISOString(),
  });
  writeAll(hikes);
}

export function removePendingHike(id: string): void {
  writeAll(readAll().filter((h) => h.id !== id));
}

// attempts to sync every queued hike to the backend. Successes are removed
// from the queue; a hike that still fails (still offline, or the backend
// is genuinely unreachable) is left in place for the next attempt --
// callers don't need to distinguish why, just that it'll keep retrying
export async function syncPendingHikes(): Promise<{ synced: number; remaining: number }> {
  let synced = 0;
  for (const hike of readAll()) {
    try {
      await logHike(hike.distanceM, hike.movingTimeS, hike.osmId ?? undefined);
      removePendingHike(hike.id);
      synced += 1;
    } catch {
      // leave it queued -- see comment above
    }
  }
  return { synced, remaining: listPendingHikes().length };
}
