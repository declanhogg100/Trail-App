import { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { router } from 'expo-router';
import {
  estimateTrailTime,
  EstimateTimeResponse,
  getTrail,
  getTrailGeometry,
  likeTrail,
  listLikedTrails,
  TrailDetail,
  unlikeTrail,
} from '../api';
import { useActiveHike } from '../activeHike';
import { formatDuration, hikeDistanceM } from '../format';
import { haversineMeters } from '../geo';
import { getCurrentLocation } from '../location';
import { downloadTrail, getOfflineTrail, isTrailDownloaded, removeOfflineTrail } from '../offlineTrails';
import { colors } from '../theme';

// beyond this, you're almost certainly not at the trailhead yet -- a
// friendly nudge to get there first, not a hard block (GPS/trail-start
// points are both approximate, and you can always start anyway)
const FAR_FROM_TRAIL_M = 1500;

// Shared between the full-screen trail detail route (app/trail/[osmId].tsx,
// reached from Explore/Liked/History) and the in-map details half-sheet
// (app/index.tsx, reached from a map marker or search result) -- same data,
// same actions, just rendered inside different containers.
export function TrailDetailContent({
  osmId,
  onLoaded,
}: {
  osmId: number;
  onLoaded?: (trail: TrailDetail) => void;
}) {
  const [trail, setTrail] = useState<TrailDetail | null>(null);
  const [isLiked, setIsLiked] = useState(false);
  const [estimate, setEstimate] = useState<EstimateTimeResponse | null>(null);
  const [error, setError] = useState(false);
  const [offline, setOffline] = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState<{ done: number; total: number } | null>(null);
  const [farFromTrail, setFarFromTrail] = useState<{ distanceKm: number } | null>(null);
  const { status: hikeStatus, start: startHike } = useActiveHike();

  useEffect(() => {
    // deferred via .then() rather than called synchronously in the effect
    // body -- isTrailDownloaded() is itself synchronous, but setState needs
    // to happen in a microtask continuation, same reasoning as elsewhere
    Promise.resolve()
      .then(() => isTrailDownloaded(osmId))
      .then(setDownloaded);

    getTrail(osmId)
      .then((result) => {
        setOffline(false);
        setTrail(result);
        onLoaded?.(result);
      })
      .catch(() => {
        // no network (or the request otherwise failed) -- fall back to a
        // previously downloaded copy instead of just showing an error, if
        // one's available. Genuinely no connection AND no download yet is
        // still a real error, so that case falls through to setError below.
        const cached = getOfflineTrail(osmId);
        if (cached) {
          setOffline(true);
          setTrail(cached.detail);
          onLoaded?.(cached.detail);
        } else {
          setError(true);
        }
      });

    // same reasoning as the estimate fetch below -- not knowing whether
    // it's liked (e.g. while offline) shouldn't block viewing the trail
    // itself, so this failing quietly just leaves isLiked at its default
    listLikedTrails()
      .then((liked) => setIsLiked(liked.some((t) => t.osm_id === osmId)))
      .catch(() => {});

    // a missing estimate (e.g. a rare per-trail profile build failure)
    // shouldn't block the rest of the trail's details from showing -- just
    // silently omit the estimate section rather than surfacing an error
    estimateTrailTime(osmId)
      .then(setEstimate)
      .catch(() => {});
    // onLoaded is expected to be a stable identity from the caller (or omitted) -- including it
    // here would refetch on every render for callers that pass an inline function
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [osmId]);

  const toggleLike = async () => {
    try {
      if (isLiked) {
        await unlikeTrail(osmId);
      } else {
        await likeTrail(osmId);
      }
      setIsLiked(!isLiked);
    } catch {
      Alert.alert('Couldn’t update', 'Please check your connection and try again.');
    }
  };

  const beginHike = async () => {
    try {
      await startHike(trail!.name, osmId);
      router.push('/active-hike');
    } catch (err) {
      // startHike()'s own thrown messages are already written for a user to
      // read (e.g. explaining the "Always" location requirement) -- shown
      // as an alert rather than inline text, so it reads as a normal app
      // dialog instead of a permanent red banner stuck on the screen
      Alert.alert('Can’t start hike', err instanceof Error ? err.message : 'Please try again.');
    }
  };

  const handleStartHike = async () => {
    // a hike's already running (possibly for a different trail) -- don't
    // silently overwrite it, just jump to the live tracking screen
    if (hikeStatus !== 'idle') {
      router.push('/active-hike');
      return;
    }

    // advisory only: if we can't tell where you are or where the trail
    // starts, don't let that block starting the hike -- just skip the check
    try {
      const [here, geometry] = await Promise.all([
        getCurrentLocation(),
        getTrailGeometry(osmId).catch(() => getOfflineTrail(osmId)?.geometry ?? null),
      ]);
      if (geometry) {
        const [startLon, startLat] = geometry.lines[0][0];
        const distanceM = haversineMeters(here.lat, here.lon, startLat, startLon);
        if (distanceM > FAR_FROM_TRAIL_M) {
          setFarFromTrail({ distanceKm: distanceM / 1000 });
          return;
        }
      }
    } catch {
      // see comment above
    }

    await beginHike();
  };

  const toggleDownload = async () => {
    if (downloaded) {
      removeOfflineTrail(osmId);
      setDownloaded(false);
      return;
    }
    setDownloading(true);
    setDownloadProgress(null);
    try {
      await downloadTrail(osmId, (done, total) => setDownloadProgress({ done, total }));
      setDownloaded(true);
      Alert.alert('Downloaded', 'Find downloaded trails in the Liked tab.');
    } catch (err) {
      console.error('download failed', err);
      Alert.alert('Download failed', 'Please check your connection and try again.');
    } finally {
      setDownloading(false);
      setDownloadProgress(null);
    }
  };

  if (error) {
    return (
      <View style={styles.center}>
        <Text style={styles.error}>Couldn&apos;t load this trail.</Text>
      </View>
    );
  }

  if (!trail) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.maroonLight} />
      </View>
    );
  }

  return (
    <View>
      <Text style={styles.title}>{trail.name}</Text>
      <Text style={styles.biome}>{trail.biome_name}</Text>
      {offline && <Text style={styles.offlineBadge}>Showing downloaded copy — offline</Text>}

      <Pressable style={[styles.likeButton, isLiked && styles.likeButtonActive]} onPress={toggleLike}>
        <Text style={[styles.likeButtonText, isLiked && styles.likeButtonTextActive]}>
          {isLiked ? 'Liked' : 'Like this trail'}
        </Text>
      </Pressable>

      <Pressable style={styles.downloadButton} onPress={toggleDownload} disabled={downloading}>
        {downloading && <ActivityIndicator size="small" color={colors.text} style={styles.downloadSpinner} />}
        <Text style={styles.downloadButtonText}>
          {downloading
            ? downloadProgress
              ? `Downloading map tiles ${downloadProgress.done}/${downloadProgress.total}`
              : 'Downloading'
            : downloaded
              ? 'Downloaded for offline use — tap to remove'
              : 'Download for offline use'}
        </Text>
      </Pressable>

      <Pressable style={styles.startHikeButton} onPress={handleStartHike}>
        <Text style={styles.startHikeButtonText}>
          {hikeStatus === 'idle' ? 'Start Hike' : 'Hike in progress — view'}
        </Text>
      </Pressable>

      <View style={styles.statsGrid}>
        {estimate && (
          <Stat
            label="Est. time (for you)"
            value={`${formatDuration(estimate.range_low_seconds)} – ${formatDuration(estimate.range_high_seconds)}`}
          />
        )}
        <Stat
          label="Distance"
          value={`${(hikeDistanceM(trail.distance_m, trail.is_loop) / 1000).toFixed(1)} km`}
        />
        <Stat label="Route" value={trail.is_loop ? 'Loop' : 'Out & back'} />
        <Stat label="Elevation gain" value={`${Math.round(trail.elevation_gain_m)} m`} />
        <Stat label="Peak elevation" value={`${Math.round(trail.peak_elevation_m)} m`} />
        <Stat label="Peak prominence" value={`${Math.round(trail.peak_prominence_m)} m`} />
        <Stat label="Tree cover" value={`${Math.round(trail.tree_cover_pct)}%`} />
        <Stat label="Realm" value={trail.realm} />
      </View>

      <Text style={styles.ecoName}>{trail.eco_name}</Text>

      <Modal
        visible={farFromTrail !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setFarFromTrail(null)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>You&apos;re far from this trail</Text>
            <Text style={styles.modalMessage}>
              You&apos;re about {farFromTrail?.distanceKm.toFixed(1)} km from the trailhead. Consider
              getting closer before starting, so your tracked route begins in the right place.
            </Text>
            <View style={styles.modalButtonRow}>
              <Pressable style={styles.modalExitButton} onPress={() => setFarFromTrail(null)}>
                <Text style={styles.modalExitButtonText}>Exit</Text>
              </Pressable>
              <Pressable
                style={styles.modalConfirmButton}
                onPress={() => {
                  setFarFromTrail(null);
                  beginHike();
                }}
              >
                <Text style={styles.modalConfirmButtonText}>Start Hike</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { alignItems: 'center', justifyContent: 'center', padding: 32 },
  error: { color: colors.error },
  title: { fontSize: 24, fontWeight: '700', color: colors.text },
  biome: { fontSize: 15, color: colors.textSecondary, marginTop: 4 },
  likeButton: {
    marginTop: 16,
    paddingVertical: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.border,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  likeButtonActive: { backgroundColor: colors.maroon, borderColor: colors.maroon },
  likeButtonText: { fontSize: 15, fontWeight: '600', color: colors.text },
  likeButtonTextActive: { color: colors.white },
  offlineBadge: { fontSize: 12, color: colors.warning, marginTop: 6, fontWeight: '600' },
  downloadButton: {
    marginTop: 10,
    paddingVertical: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.border,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  downloadButtonText: { fontSize: 15, fontWeight: '600', color: colors.text },
  downloadSpinner: { marginRight: 2 },
  startHikeButton: {
    marginTop: 12,
    paddingVertical: 12,
    borderRadius: 8,
    backgroundColor: colors.maroon,
    alignItems: 'center',
  },
  startHikeButtonText: { fontSize: 16, fontWeight: '700', color: colors.white },
  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 24, gap: 16 },
  stat: { width: '45%' },
  statValue: { fontSize: 18, fontWeight: '700', color: colors.text },
  statLabel: { fontSize: 13, color: colors.textSecondary, marginTop: 2 },
  ecoName: { fontSize: 13, color: colors.textMuted, marginTop: 24, fontStyle: 'italic' },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.6)',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
  },
  modalCard: {
    width: '100%',
    backgroundColor: colors.surfaceRaised,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    padding: 20,
  },
  modalTitle: { fontSize: 18, fontWeight: '700', color: colors.text },
  modalMessage: { fontSize: 14, color: colors.textSecondary, marginTop: 8, lineHeight: 20 },
  modalButtonRow: { flexDirection: 'row', gap: 12, marginTop: 20 },
  modalExitButton: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
  },
  modalExitButtonText: { fontSize: 15, fontWeight: '600', color: colors.text },
  modalConfirmButton: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 8,
    backgroundColor: colors.maroon,
    alignItems: 'center',
  },
  modalConfirmButtonText: { fontSize: 15, fontWeight: '600', color: colors.white },
});
