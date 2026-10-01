import { Directory, File, Paths } from 'expo-file-system';
import { getOfflineTileManifest, getTrail, getTrailGeometry, offlineTileUrl, TrailDetail, TrailGeometry } from './api';

// everything needed to view a trail's details and draw its route on the
// map without a network connection -- the two pieces already come from
// separate endpoints, bundled together here since they're always used
// (and downloaded/removed) as a pair
export type OfflineTrail = {
  detail: TrailDetail;
  geometry: TrailGeometry;
};

const offlineDir = new Directory(Paths.document, 'offline-trails');

function detailFileFor(osmId: number): File {
  return new File(offlineDir, `${osmId}.json`);
}

function tilesDirFor(osmId: number): Directory {
  return new Directory(offlineDir, `${osmId}-tiles`);
}

function ensureDir() {
  if (!offlineDir.exists) offlineDir.create();
}

export function isTrailDownloaded(osmId: number): boolean {
  return detailFileFor(osmId).exists;
}

export function getOfflineTrail(osmId: number): OfflineTrail | null {
  const file = detailFileFor(osmId);
  if (!file.exists) return null;
  try {
    return JSON.parse(file.textSync()) as OfflineTrail;
  } catch {
    // a corrupted/partial cache file shouldn't crash the caller -- treat it
    // the same as not having one downloaded at all
    return null;
  }
}

// a file:// directory MapLibre's RasterSource can read tiles from directly
// via a "{tilesDir}/{z}/{x}/{y}.png" URL template -- null if this trail's
// terrain tiles were never downloaded (or the download only partially
// completed), in which case the map falls back to a blank background with
// just the route line and position, still fully usable
export function getOfflineTilesDir(osmId: number): string | null {
  const dir = tilesDirFor(osmId);
  return dir.exists ? dir.uri : null;
}

export async function downloadTrail(osmId: number, onProgress?: (done: number, total: number) => void): Promise<void> {
  const [detail, geometry] = await Promise.all([getTrail(osmId), getTrailGeometry(osmId)]);
  const manifest = await getOfflineTileManifest(osmId);

  // tiles are downloaded into a temporary directory and only swapped into
  // place once every tile succeeds -- a download that fails partway through
  // deletes the temp dir and rethrows, leaving nothing behind for
  // isTrailDownloaded() (which keys off the detail file below) to mistake
  // for a completed download
  ensureDir();
  const finalDir = tilesDirFor(osmId);
  const tmpDir = new Directory(offlineDir, `${osmId}-tiles-tmp`);
  if (tmpDir.exists) tmpDir.delete();
  tmpDir.create();

  let done = 0;
  try {
    for (const tile of manifest.tiles) {
      // multiple tiles share the same z/x (different y), so this directory
      // is revisited across loop iterations -- only create it the first time
      const tileDir = new Directory(tmpDir, String(tile.z), String(tile.x));
      if (!tileDir.exists) tileDir.create({ intermediates: true });
      await File.downloadFileAsync(offlineTileUrl(osmId, tile), tileDir);
      done += 1;
      onProgress?.(done, manifest.tiles.length);
    }
  } catch (err) {
    tmpDir.delete();
    throw err;
  }

  if (finalDir.exists) finalDir.delete();
  await tmpDir.move(finalDir);

  // written only once every tile has downloaded successfully -- this file's
  // presence is what isTrailDownloaded()/getOfflineTrail() treat as "this
  // trail is available offline", so it must be the very last thing written
  detailFileFor(osmId).write(JSON.stringify({ detail, geometry }));
}

export function listOfflineTrails(): { osmId: number; trail: OfflineTrail }[] {
  if (!offlineDir.exists) return [];
  const entries: { osmId: number; trail: OfflineTrail }[] = [];
  for (const entry of offlineDir.list()) {
    if (!(entry instanceof File) || !entry.name.endsWith('.json')) continue;
    const osmId = Number(entry.name.slice(0, -'.json'.length));
    const trail = getOfflineTrail(osmId);
    if (trail) entries.push({ osmId, trail });
  }
  return entries;
}

export function removeOfflineTrail(osmId: number): void {
  const file = detailFileFor(osmId);
  if (file.exists) file.delete();
  const tilesDir = tilesDirFor(osmId);
  if (tilesDir.exists) tilesDir.delete();
}
