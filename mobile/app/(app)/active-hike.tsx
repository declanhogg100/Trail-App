import { useEffect, useState } from 'react';
import { ActivityIndicator, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { router } from 'expo-router';
import { AppleMaps, GoogleMaps } from 'expo-maps';
import { getTrailGeometry, logHike } from '../../src/api';
import { useActiveHike } from '../../src/activeHike';
import { formatElapsed, formatPace, metersToFeet, metersToMiles } from '../../src/format';

const TRAIL_COLOR = '#2e7d32';
// the walked path needs to read as clearly distinct from the planned trail
// route at a glance, so it uses a different hue entirely rather than a
// shade of the same green
const WALKED_COLOR = '#1e88e5';

type FinishedSummary = { distanceM: number; elapsedS: number; saveError: string | null };

export default function ActiveHikeScreen() {
  const { status, trailName, osmId, distanceM, elevationGainM, elapsedMs, pathCoords, currentPosition, pause, resume, finish } =
    useActiveHike();
  const [error, setError] = useState<string | null>(null);
  const [finishing, setFinishing] = useState(false);
  const [summary, setSummary] = useState<FinishedSummary | null>(null);
  const [trailLines, setTrailLines] = useState<[number, number][][] | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (osmId == null) return null;
      try {
        const geometry = await getTrailGeometry(osmId);
        return geometry.lines;
      } catch {
        return null;
      }
    };
    load().then((lines) => {
      if (!cancelled) setTrailLines(lines);
    });
    return () => {
      cancelled = true;
    };
  }, [osmId]);

  const handlePauseResume = async () => {
    setError(null);
    try {
      if (status === 'active') {
        pause();
      } else {
        await resume();
      }
    } catch (err) {
      setError(String(err));
    }
  };

  const handleFinish = async () => {
    // capture the numbers and reset tracking immediately -- logHike()
    // finishing later shouldn't leave the live-tracking UI hanging around
    const result = finish();
    setFinishing(true);
    try {
      await logHike(result.distanceM, result.elapsedS, result.osmId ?? undefined);
      setSummary({ ...result, saveError: null });
    } catch (err) {
      setSummary({ ...result, saveError: String(err) });
    } finally {
      setFinishing(false);
    }
  };

  if (summary) {
    return (
      <View style={styles.center}>
        <Text style={styles.emptyText}>Hike saved</Text>
        <View style={styles.statsRow}>
          <Stat label="Distance" value={`${metersToMiles(summary.distanceM).toFixed(2)} mi`} />
          <Stat label="Time" value={formatElapsed(summary.elapsedS * 1000)} />
        </View>
        {summary.saveError && (
          <Text style={styles.error}>Couldn&apos;t save to your hike history: {summary.saveError}</Text>
        )}
        <Pressable style={styles.secondaryButton} onPress={() => setSummary(null)}>
          <Text style={styles.secondaryButtonText}>Done</Text>
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

  const polylines = [
    ...(trailLines
      ? trailLines.map((line) => ({
          coordinates: line.map(([lon, lat]) => ({ latitude: lat, longitude: lon })),
          color: TRAIL_COLOR,
          width: 3,
        }))
      : []),
    ...(pathCoords.length > 1
      ? [
          {
            coordinates: pathCoords.map(([lon, lat]) => ({ latitude: lat, longitude: lon })),
            color: WALKED_COLOR,
            width: 4,
          },
        ]
      : []),
  ];

  // camera starts wherever GPS first fixes, falling back to the trail's own
  // start point until that first fix arrives -- either way there's always
  // something reasonable to center on rather than an arbitrary default
  const initialFocus = currentPosition ?? trailLines?.[0]?.[0] ?? null;
  const cameraPosition = initialFocus
    ? { coordinates: { latitude: initialFocus[1], longitude: initialFocus[0] }, zoom: 15 }
    : undefined;

  return (
    <View style={styles.container}>
      {Platform.OS === 'ios' ? (
        <AppleMaps.View
          style={styles.map}
          cameraPosition={cameraPosition}
          polylines={polylines}
          properties={{ isMyLocationEnabled: true }}
        />
      ) : (
        <GoogleMaps.View
          style={styles.map}
          cameraPosition={cameraPosition}
          polylines={polylines}
          properties={{ isMyLocationEnabled: true }}
        />
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

        {error && <Text style={styles.error}>{error}</Text>}

        <View style={styles.buttonRow}>
          <Pressable style={styles.pauseButton} onPress={handlePauseResume}>
            <Text style={styles.pauseButtonText}>{status === 'active' ? 'Pause' : 'Resume'}</Text>
          </Pressable>
          <Pressable style={styles.finishButton} onPress={handleFinish} disabled={finishing}>
            <Text style={styles.finishButtonText}>{finishing ? 'Saving…' : 'Finish'}</Text>
          </Pressable>
        </View>
      </View>

      {!currentPosition && (
        <View style={styles.loadingBadge}>
          <ActivityIndicator />
        </View>
      )}
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
  container: { flex: 1 },
  map: { flex: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 32, backgroundColor: '#fff' },
  emptyText: { fontSize: 20, fontWeight: '700', marginBottom: 4 },
  emptySubtext: { fontSize: 14, color: '#666', marginBottom: 20, textAlign: 'center' },
  loadingBadge: {
    position: 'absolute',
    top: 16,
    right: 16,
    backgroundColor: 'white',
    borderRadius: 20,
    padding: 8,
    shadowColor: '#000',
    shadowOpacity: 0.2,
    shadowRadius: 4,
    elevation: 3,
  },
  panel: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    backgroundColor: '#fff',
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    paddingTop: 12,
    paddingBottom: 24,
    paddingHorizontal: 20,
    shadowColor: '#000',
    shadowOpacity: 0.25,
    shadowRadius: 8,
    elevation: 8,
  },
  panelHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  trailName: { fontSize: 15, fontWeight: '600', maxWidth: '80%' },
  pausedBadge: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 4,
    backgroundColor: '#f5a623',
    color: '#fff',
    fontSize: 11,
    fontWeight: '700',
  },
  statsRow: { flexDirection: 'row', justifyContent: 'space-around', marginVertical: 12 },
  stat: { alignItems: 'center' },
  statValue: { fontSize: 18, fontWeight: '700', fontVariant: ['tabular-nums'] },
  statLabel: { fontSize: 11, color: '#666', marginTop: 2 },
  error: { color: 'red', textAlign: 'center', marginBottom: 8, fontSize: 13 },
  buttonRow: { flexDirection: 'row', justifyContent: 'space-around' },
  pauseButton: {
    paddingVertical: 10,
    paddingHorizontal: 28,
    borderRadius: 24,
    backgroundColor: '#333',
  },
  pauseButtonText: { color: '#fff', fontSize: 15, fontWeight: '600' },
  finishButton: {
    paddingVertical: 10,
    paddingHorizontal: 28,
    borderRadius: 24,
    backgroundColor: '#e0245e',
  },
  finishButtonText: { color: '#fff', fontSize: 15, fontWeight: '600' },
  secondaryButton: {
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#333',
  },
  secondaryButtonText: { fontSize: 15, fontWeight: '600', color: '#333' },
});
