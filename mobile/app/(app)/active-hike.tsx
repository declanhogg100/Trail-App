import { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { router } from 'expo-router';
import { Camera, GeoJSONSource, Layer, Map as MapLibreMap, RasterSource, UserLocation } from '@maplibre/maplibre-react-native';
import { getTrailGeometry, logHike, offlineTileUrlTemplate } from '../../src/api';
import { useActiveHike } from '../../src/activeHike';
import { formatElapsed, formatPace, metersToFeet, metersToMiles } from '../../src/format';
import { getOfflineTilesDir, getOfflineTrail } from '../../src/offlineTrails';
import { enqueuePendingHike } from '../../src/pendingHikes';
import { colors } from '../../src/theme';

// no base style at all -- the only imagery this screen ever shows is our
// own terrain tiles (local if downloaded, live from our own server
// otherwise), painted on top of this blank canvas. No third-party online
// base map here on purpose -- see the tile-source logic below for why.
const BLANK_STYLE = { version: 8 as const, sources: {}, layers: [] };
const OFFLINE_TILE_ZOOMS = { min: 13, max: 15 };

// map line colors are deliberately not drawn from the app's black/maroon
// theme -- a planned route and a recorded track need to read as two
// distinct things at a glance against whatever terrain is underneath them,
// which matters more here than matching the brand palette
const TRAIL_COLOR = '#2e7d32';
const WALKED_COLOR = '#1e88e5';

// a hike this short is almost always an accidental start/stop, not a real
// hike -- saving it would pollute hike history and skew the time
// estimator's per-user pace personalization, so it's dropped before ever
// reaching the backend rather than saved and left for manual cleanup
const MIN_HIKE_DURATION_S = 7 * 60;

type FinishedSummary = {
  distanceM: number;
  elapsedS: number;
  elevationGainM: number;
  trailName: string | null;
  saved: boolean;
  queued: boolean;
  saveError: string | null;
};

export default function ActiveHikeScreen() {
  const {
    status,
    trailName,
    osmId,
    distanceM,
    elevationGainM,
    elapsedMs,
    pathCoords,
    currentPosition,
    pause,
    resume,
    finish,
  } = useActiveHike();
  const [finishing, setFinishing] = useState(false);
  const [summary, setSummary] = useState<FinishedSummary | null>(null);
  const [trailLines, setTrailLines] = useState<[number, number][][] | null>(null);
  const [tilesDir, setTilesDir] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (osmId == null) return null;
      try {
        const geometry = await getTrailGeometry(osmId);
        return geometry.lines;
      } catch {
        // no signal (the exact scenario this app needs to handle -- most
        // trails are out of cell range) -- fall back to a downloaded copy
        // if this trail was saved for offline use ahead of time
        return getOfflineTrail(osmId)?.geometry.lines ?? null;
      }
    };
    load().then((lines) => {
      if (!cancelled) setTrailLines(lines);
    });
    Promise.resolve()
      .then(() => (osmId == null ? null : getOfflineTilesDir(osmId)))
      .then((dir) => {
        if (!cancelled) setTilesDir(dir);
      });
    return () => {
      cancelled = true;
    };
  }, [osmId]);

  const handlePauseResume = async () => {
    try {
      if (status === 'active') {
        pause();
      } else {
        await resume();
      }
    } catch (err) {
      Alert.alert('Couldn’t resume tracking', err instanceof Error ? err.message : 'Please try again.');
    }
  };

  const handleFinish = async () => {
    // capture the numbers and reset tracking immediately -- logHike()
    // finishing later shouldn't leave the live-tracking UI hanging around
    const result = finish();

    if (result.elapsedS < MIN_HIKE_DURATION_S) {
      setSummary({ ...result, saved: false, queued: false, saveError: null });
      return;
    }

    setFinishing(true);
    try {
      await logHike(result.distanceM, result.elapsedS, result.osmId ?? undefined);
      setSummary({ ...result, saved: true, queued: false, saveError: null });
    } catch {
      // couldn't reach the backend -- the expected case is finishing a
      // hike while still out of signal, which this app is specifically
      // built to make possible. Queue it locally instead of losing it;
      // it'll sync automatically next time the History tab is opened
      // with a connection, or the app relaunches with one.
      try {
        enqueuePendingHike(result.distanceM, result.elapsedS, result.osmId);
        setSummary({ ...result, saved: false, queued: true, saveError: null });
      } catch (queueErr) {
        setSummary({ ...result, saved: false, queued: false, saveError: String(queueErr) });
      }
    } finally {
      setFinishing(false);
    }
  };

  if (summary) {
    const tooShort = !summary.saved && !summary.queued && !summary.saveError;
    const statusText = tooShort
      ? 'Hike too short to save'
      : summary.queued
        ? 'Saved locally — will sync when back in range'
        : summary.saveError
          ? "Couldn't save hike"
          : 'Hike saved';
    return (
      <View style={styles.summaryContainer}>
        <Text style={styles.summaryTitle}>{summary.trailName ?? 'Hike complete'}</Text>
        <Text style={styles.summarySubtitle}>{statusText}</Text>

        <View style={styles.statsGrid}>
          <Stat grid label="Distance" value={`${metersToMiles(summary.distanceM).toFixed(2)} mi`} />
          <Stat grid label="Time" value={formatElapsed(summary.elapsedS * 1000)} />
          <Stat grid label="Pace" value={formatPace(summary.elapsedS * 1000, summary.distanceM)} />
          <Stat
            grid
            label="Elevation gain"
            value={`${Math.round(metersToFeet(summary.elevationGainM))} ft`}
          />
        </View>

        <Pressable style={styles.doneButton} onPress={() => setSummary(null)}>
          <Text style={styles.doneButtonText}>Done</Text>
        </Pressable>
      </View>
    );
  }

  if (status === 'idle') {
    return (
      <View style={styles.center}>
        <Text style={styles.emptyText}>No hike in progress</Text>
        <Text style={styles.emptySubtext}>Start one from a trail&apos;s detail page.</Text>
        <Pressable style={styles.secondaryButton} onPress={() => router.push('/')}>
          <Text style={styles.secondaryButtonText}>Find a trail</Text>
        </Pressable>
      </View>
    );
  }

  // camera starts wherever GPS first fixes, falling back to the trail's own
  // start point until that first fix arrives -- either way there's always
  // something reasonable to center on rather than an arbitrary default
  const initialFocus = currentPosition ?? trailLines?.[0]?.[0] ?? null;

  // prefer the local copy (instant, works with zero signal) if this trail
  // was downloaded ahead of time; otherwise fall back to fetching tiles
  // live from our own backend, one at a time, as long as you have signal
  // right now -- there's no reason to force a download first just because
  // you happen to have a connection at the moment
  const tileUrlTemplate = tilesDir
    ? `${tilesDir.replace(/\/$/, '')}/{z}/{x}/{y}.png`
    : osmId != null
      ? offlineTileUrlTemplate(osmId)
      : null;

  return (
    <View style={styles.container}>
      <MapLibreMap style={styles.map} mapStyle={BLANK_STYLE}>
        <Camera
          initialViewState={initialFocus ? { center: initialFocus, zoom: 15 } : undefined}
          trackUserLocation="default"
        />

        <UserLocation />

        {tileUrlTemplate && (
          <RasterSource
            id="offline-terrain"
            tiles={[tileUrlTemplate]}
            tileSize={256}
            minzoom={OFFLINE_TILE_ZOOMS.min}
            maxzoom={OFFLINE_TILE_ZOOMS.max}
          >
            <Layer type="raster" id="offline-terrain-layer" />
          </RasterSource>
        )}

        {trailLines && (
          <GeoJSONSource
            id="trail-route"
            data={{ type: 'MultiLineString', coordinates: trailLines }}
          >
            <Layer
              type="line"
              id="trail-route-layer"
              layout={{ 'line-cap': 'round', 'line-join': 'round' }}
              paint={{ 'line-color': TRAIL_COLOR, 'line-width': 3 }}
            />
          </GeoJSONSource>
        )}

        {pathCoords.length > 1 && (
          <GeoJSONSource id="walked-path" data={{ type: 'LineString', coordinates: pathCoords }}>
            <Layer
              type="line"
              id="walked-path-layer"
              layout={{ 'line-cap': 'round', 'line-join': 'round' }}
              paint={{ 'line-color': WALKED_COLOR, 'line-width': 4 }}
            />
          </GeoJSONSource>
        )}
      </MapLibreMap>

      <View style={styles.panel}>
        <View style={styles.panelHeader}>
          <Text style={styles.trailName} numberOfLines={1}>
            {trailName}
          </Text>
          {status === 'paused' && <Text style={styles.pausedBadge}>PAUSED</Text>}
        </View>

        <View style={styles.statsRow}>
          <Stat label="Time" value={formatElapsed(elapsedMs)} />
          <Stat label="Distance" value={`${metersToMiles(distanceM).toFixed(2)} mi`} />
          <Stat label="Pace" value={formatPace(elapsedMs, distanceM)} />
          <Stat label="Elev. gain" value={`${Math.round(metersToFeet(elevationGainM))} ft`} />
        </View>

        <View style={styles.buttonRow}>
          <Pressable style={styles.pauseButton} onPress={handlePauseResume}>
            <Text style={styles.pauseButtonText}>{status === 'active' ? 'Pause' : 'Resume'}</Text>
          </Pressable>
          <Pressable style={styles.finishButton} onPress={handleFinish} disabled={finishing}>
            <Text style={styles.finishButtonText}>{finishing ? 'Saving' : 'Finish'}</Text>
          </Pressable>
        </View>
      </View>

      {!currentPosition && (
        <View style={styles.loadingBadge}>
          <ActivityIndicator color={colors.maroonLight} />
        </View>
      )}
    </View>
  );
}

function Stat({ label, value, grid }: { label: string; value: string; grid?: boolean }) {
  return (
    <View style={grid ? styles.gridStat : styles.stat}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  map: { flex: 1 },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
    backgroundColor: colors.background,
  },
  emptyText: { fontSize: 20, fontWeight: '700', marginBottom: 4, color: colors.text },
  emptySubtext: { fontSize: 14, color: colors.textSecondary, marginBottom: 20, textAlign: 'center' },
  loadingBadge: {
    position: 'absolute',
    top: 16,
    right: 16,
    backgroundColor: colors.surface,
    borderRadius: 20,
    padding: 8,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  panel: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    backgroundColor: colors.surface,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    paddingTop: 12,
    paddingBottom: 24,
    paddingHorizontal: 20,
  },
  panelHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  trailName: { fontSize: 15, fontWeight: '600', maxWidth: '80%', color: colors.text },
  pausedBadge: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 4,
    backgroundColor: colors.warning,
    color: colors.white,
    fontSize: 11,
    fontWeight: '700',
  },
  statsRow: { flexDirection: 'row', justifyContent: 'space-around', marginVertical: 12 },
  stat: { alignItems: 'center' },
  gridStat: { width: '42%' },
  statValue: { fontSize: 18, fontWeight: '700', fontVariant: ['tabular-nums'], color: colors.text },
  statLabel: { fontSize: 11, color: colors.textSecondary, marginTop: 2 },
  buttonRow: { flexDirection: 'row', justifyContent: 'space-around' },
  pauseButton: {
    paddingVertical: 10,
    paddingHorizontal: 28,
    borderRadius: 24,
    backgroundColor: colors.surfaceRaised,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  pauseButtonText: { color: colors.text, fontSize: 15, fontWeight: '600' },
  finishButton: {
    paddingVertical: 10,
    paddingHorizontal: 28,
    borderRadius: 24,
    backgroundColor: colors.maroon,
  },
  finishButtonText: { color: colors.white, fontSize: 15, fontWeight: '600' },
  secondaryButton: {
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.border,
  },
  secondaryButtonText: { fontSize: 15, fontWeight: '600', color: colors.text },

  // finish summary -- styled like TrailDetailContent's own layout (title,
  // then a wrapping stats grid with real breathing room) rather than the
  // cramped single-row pair of numbers this used to be
  summaryContainer: {
    flex: 1,
    backgroundColor: colors.background,
    paddingHorizontal: 24,
    paddingTop: 48,
  },
  summaryTitle: { fontSize: 24, fontWeight: '700', color: colors.text },
  summarySubtitle: { fontSize: 15, color: colors.textSecondary, marginTop: 4 },
  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 28, gap: 20 },
  doneButton: {
    marginTop: 32,
    paddingVertical: 12,
    borderRadius: 8,
    backgroundColor: colors.maroon,
    alignItems: 'center',
  },
  doneButtonText: { fontSize: 16, fontWeight: '700', color: colors.white },
});
