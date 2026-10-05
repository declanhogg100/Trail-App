import { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { router } from 'expo-router';
import {
  Camera,
  type CameraRef,
  GeoJSONSource,
  Layer,
  type LngLatBounds,
  Map as MapLibreMap,
  RasterSource,
  UserLocation,
} from '@maplibre/maplibre-react-native';
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
// 10-12 come from recommender's CONTEXT_ZOOMS (a wide, coarse render for
// zoomed-out surrounding geography), 13-15 from OFFLINE_ZOOMS (a tight,
// fine-detail render of the immediate trail corridor) -- both are served
// by the same per-tile endpoint/local cache, so one RasterSource spanning
// the whole range is all that's needed; MapLibre requests whichever zoom
// it actually needs as you zoom.
const OFFLINE_TILE_ZOOMS = { min: 10, max: 15 };

// how far past the trail's own bounding box the camera is allowed to pan
// and zoom out to. Safely less than the server's own CONTEXT_BUFFER_M
// (12km) -- the render buffer is measured from the trail LINE, but this is
// the padding on the trail's bounding BOX, so staying a little inside the
// render buffer keeps the locked rectangle's corners (which stick out
// further from the line than its edges do) from poking past what's
// actually been rendered.
const MAX_BOUNDS_BUFFER_M = 10_000;

// map line colors are deliberately not drawn from the app's black/maroon
// theme -- a planned route and a recorded track need to read as two
// distinct things at a glance against whatever terrain is underneath them,
// which matters more here than matching the brand palette
const TRAIL_COLOR = '#2e7d32';
const TRAIL_WIDTH = 4;
// neither AppleMaps/GoogleMaps nor MapLibre expose a native outline/casing
// property on a polyline -- a faint halo is faked by drawing a wider,
// translucent line of the same color underneath the real one. Same
// treatment as the Search/Map screen's trail line.
const TRAIL_OUTLINE_COLOR = 'rgba(46, 125, 50, 0.35)';
const TRAIL_OUTLINE_WIDTH = 8;
const WALKED_COLOR = '#1e88e5';

// start/end trailhead markers -- white reads clearly as "the beginning"
// against any terrain color underneath; maroon ties "the end" (for an
// out-and-back, its literal turnaround point) back to the app's own accent
// color rather than inventing a third unrelated hue
const TRAIL_START_COLOR = '#ffffff';
const TRAIL_END_COLOR = colors.maroonLight;
const TRAIL_MARKER_RADIUS = 6;

// approximates the standard slippy-map zoom convention (span halves each
// zoom level) -- not pixel-perfect since it ignores screen width/aspect
// ratio, but close enough for "pick a minZoom that keeps the trail's own
// bounding box from being zoomed out past"
function zoomForSpan(spanDeg: number): number {
  return Math.log2(360 / spanDeg) + 1;
}

// the trail's own bounding box, padded by MAX_BOUNDS_BUFFER_M -- this is
// what the camera gets locked to (see maxBounds/minZoom on Camera below),
// so you can never pan or zoom out to where the map runs out of real,
// rendered terrain and goes blank. A single whole-world background image
// was tried first (see git history) -- there's no resolution that looks
// right at both "whole continent" and "actually hiking" scales at once,
// since it's one fixed-detail image regardless of zoom. Locking the
// viewport to the area that's actually rendered sidesteps the problem
// entirely instead of trying to paper over it.
function boundsFromTrail(
  trailLines: [number, number][][]
): { bounds: LngLatBounds; minZoom: number } | null {
  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;
  for (const line of trailLines) {
    for (const [lon, lat] of line) {
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
  }
  if (!isFinite(minLon)) return null;

  const centerLat = (minLat + maxLat) / 2;
  const bufferDeg = MAX_BOUNDS_BUFFER_M / (111_320 * Math.max(Math.cos((centerLat * Math.PI) / 180), 0.1));

  const bounds: LngLatBounds = [minLon - bufferDeg, minLat - bufferDeg, maxLon + bufferDeg, maxLat + bufferDeg];
  const span = Math.max(bounds[2] - bounds[0], bounds[3] - bounds[1]);
  // clamped to the range tiles actually exist in -- a short trail's own
  // bbox can need a tighter zoom to fill the screen than OFFLINE_TILE_ZOOMS
  // .max, which would otherwise permanently stretch the highest-detail
  // tile available past its native resolution (blurry) with no way to
  // zoom back out of it; a very long trail's bbox could in principle need
  // a wider zoom than .min, which the floor guards symmetrically
  const minZoom = Math.min(Math.max(zoomForSpan(span), OFFLINE_TILE_ZOOMS.min), OFFLINE_TILE_ZOOMS.max);
  return { bounds, minZoom };
}

function isWithinBounds([lon, lat]: [number, number], [west, south, east, north]: LngLatBounds): boolean {
  return lon >= west && lon <= east && lat >= south && lat <= north;
}

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
    sessionId,
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
  const [geometryResolved, setGeometryResolved] = useState(false);
  const [tilesDir, setTilesDir] = useState<string | null>(null);
  const cameraRef = useRef<CameraRef>(null);

  // recomputed only when trailLines itself actually changes, not on every
  // render
  const trailBounds = useMemo(() => (trailLines ? boundsFromTrail(trailLines) : null), [trailLines]);

  // a finished hike's summary is only otherwise cleared by tapping "Done" --
  // without this, starting a new hike without dismissing the previous
  // summary first would reopen Active Hike straight onto the OLD hike's
  // finish screen instead of the new one's live map
  useEffect(() => {
    Promise.resolve().then(() => setSummary(null));
  }, [sessionId]);

  useEffect(() => {
    let cancelled = false;
    // reset immediately, not just once the fetch resolves -- otherwise a
    // new hike starting while the previous trail's geometry is still in
    // state would leave mapReady (and trailBounds/trailStart/trailEnd)
    // pointing at the OLD trail for the entire fetch, instead of correctly
    // hiding the map until the new trail's own geometry has actually loaded
    Promise.resolve().then(() => {
      setTrailLines(null);
      setGeometryResolved(false);
      setTilesDir(null);
    });
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
    load()
      .catch(() => null) // getOfflineTrail() throwing (corrupt cache, etc.) must not leave geometryResolved stuck false forever
      .then((lines) => {
        if (cancelled) return;
        setTrailLines(lines);
        // distinct from trailLines itself being null -- this fires once the
        // fetch (or its offline fallback) has definitively settled either
        // way, so the map doesn't mount with a guessed zoom before knowing
        // whether we're actually near the trail (see mapReady below)
        setGeometryResolved(true);
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

  const trailStart = trailLines?.[0]?.[0] ?? null;
  // the stored geometry for an out-and-back trail is already just the
  // one-way path to its turnaround point -- so the last coordinate of the
  // last line is exactly the right "end" marker for both loop trails
  // (where it lands back on/near the start) and out-and-back ones (where
  // it's the real far point of the hike), with no special-casing needed
  const lastLine = trailLines?.[trailLines.length - 1];
  const trailEnd = lastLine?.[lastLine.length - 1] ?? null;

  // the map doesn't mount at all until the trail geometry fetch (or its
  // offline/no-trail fallback) has settled, and we have *some* reasonable
  // point to focus on -- either a GPS fix, or (while still waiting on one)
  // the trail's own start point. Without this fallback, a GPS fix that
  // never arrives (denied permission, no signal) would leave the map stuck
  // loading forever. The very first initialViewState ends up correct
  // either way, instead of guessing zoom 15 up front and trying to correct
  // it after the native camera is already live, which is unreliable (the
  // native ref may not even be attached yet by the time such a correction
  // would fire).
  const mapReady = geometryResolved && (currentPosition !== null || trailStart !== null);

  // same bounds check the follow effect above uses -- a GPS fix outside
  // the rendered area shouldn't be the initial focus either, for the same
  // reason it shouldn't drag the camera there later
  const initialFocus =
    currentPosition && (!trailBounds || isWithinBounds(currentPosition, trailBounds.bounds))
      ? currentPosition
      : trailStart;
  // never start below the enforced floor -- a very short trail's bounds
  // can require a minZoom above the usual default of 15
  const initialZoom = Math.max(15, trailBounds?.minZoom ?? 0);

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
      {mapReady && (
        // keyed on sessionId so a new hike (even a restart of the same
        // trail) fully remounts the map -- Camera's initialViewState only
        // ever applies at mount, so without this a second hike would just
        // inherit wherever the camera was left after the first one,
        // possibly outside the new trail's maxBounds
        <MapLibreMap key={sessionId} style={styles.map} mapStyle={BLANK_STYLE}>
          <Camera
            ref={cameraRef}
            initialViewState={initialFocus ? { center: initialFocus, zoom: initialZoom } : undefined}
            minZoom={trailBounds?.minZoom}
            maxZoom={OFFLINE_TILE_ZOOMS.max}
            maxBounds={trailBounds?.bounds}
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
              {/* outline declared first so it renders underneath the real
                  trail-route-layer below */}
              <Layer
                type="line"
                id="trail-route-outline"
                layout={{ 'line-cap': 'round', 'line-join': 'round' }}
                paint={{ 'line-color': TRAIL_OUTLINE_COLOR, 'line-width': TRAIL_OUTLINE_WIDTH }}
              />
              <Layer
                type="line"
                id="trail-route-layer"
                layout={{ 'line-cap': 'round', 'line-join': 'round' }}
                paint={{ 'line-color': TRAIL_COLOR, 'line-width': TRAIL_WIDTH }}
              />
            </GeoJSONSource>
          )}

          {trailStart && (
            <GeoJSONSource id="trail-start" data={{ type: 'Point', coordinates: trailStart }}>
              <Layer
                type="circle"
                id="trail-start-layer"
                paint={{
                  'circle-radius': TRAIL_MARKER_RADIUS,
                  'circle-color': TRAIL_START_COLOR,
                  'circle-stroke-width': 2,
                  'circle-stroke-color': TRAIL_COLOR,
                }}
              />
            </GeoJSONSource>
          )}

          {/* for a loop trail this lands on/right next to trail-start --
              expected, not a bug, since a loop's start and end really are
              the same point */}
          {trailEnd && (
            <GeoJSONSource id="trail-end" data={{ type: 'Point', coordinates: trailEnd }}>
              <Layer
                type="circle"
                id="trail-end-layer"
                paint={{
                  'circle-radius': TRAIL_MARKER_RADIUS,
                  'circle-color': TRAIL_END_COLOR,
                  'circle-stroke-width': 2,
                  'circle-stroke-color': TRAIL_COLOR,
                }}
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
      )}

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

      {!mapReady && (
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
  container: { flex: 1, backgroundColor: colors.background },
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
