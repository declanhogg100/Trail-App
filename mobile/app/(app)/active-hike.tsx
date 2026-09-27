import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { router } from 'expo-router';
import { logHike } from '../../src/api';
import { useActiveHike } from '../../src/activeHike';
import { formatElapsed, formatPace, metersToFeet, metersToMiles } from '../../src/format';

type FinishedSummary = { distanceM: number; elapsedS: number; saveError: string | null };

export default function ActiveHikeScreen() {
  const { status, trailName, distanceM, elevationGainM, elapsedMs, pause, resume, finish } =
    useActiveHike();
  const [error, setError] = useState<string | null>(null);
  const [finishing, setFinishing] = useState(false);
  const [summary, setSummary] = useState<FinishedSummary | null>(null);

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

  return (
    <View style={styles.container}>
      <Text style={styles.trailName}>{trailName}</Text>
      {status === 'paused' && <Text style={styles.pausedBadge}>PAUSED</Text>}

      <Text style={styles.timer}>{formatElapsed(elapsedMs)}</Text>

      <View style={styles.statsRow}>
        <Stat label="Distance" value={`${metersToMiles(distanceM).toFixed(2)} mi`} />
        <Stat label="Elevation gain" value={`${Math.round(metersToFeet(elevationGainM))} ft`} />
        <Stat label="Pace" value={formatPace(elapsedMs, distanceM)} />
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
  container: { flex: 1, backgroundColor: '#fff', paddingTop: 24, paddingHorizontal: 24 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 32 },
  emptyText: { fontSize: 20, fontWeight: '700', marginBottom: 4 },
  emptySubtext: { fontSize: 14, color: '#666', marginBottom: 20, textAlign: 'center' },
  trailName: { fontSize: 18, fontWeight: '600', textAlign: 'center' },
  pausedBadge: {
    alignSelf: 'center',
    marginTop: 8,
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: 4,
    backgroundColor: '#f5a623',
    color: '#fff',
    fontSize: 12,
    fontWeight: '700',
  },
  timer: { fontSize: 56, fontWeight: '200', textAlign: 'center', marginVertical: 24, fontVariant: ['tabular-nums'] },
  statsRow: { flexDirection: 'row', justifyContent: 'space-around', marginVertical: 16 },
  stat: { alignItems: 'center' },
  statValue: { fontSize: 22, fontWeight: '700' },
  statLabel: { fontSize: 12, color: '#666', marginTop: 2 },
  error: { color: 'red', textAlign: 'center', marginTop: 12 },
  buttonRow: { flexDirection: 'row', justifyContent: 'space-around', marginTop: 32 },
  pauseButton: {
    paddingVertical: 14,
    paddingHorizontal: 32,
    borderRadius: 30,
    backgroundColor: '#333',
  },
  pauseButtonText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  finishButton: {
    paddingVertical: 14,
    paddingHorizontal: 32,
    borderRadius: 30,
    backgroundColor: '#e0245e',
  },
  finishButtonText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  secondaryButton: {
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#333',
  },
  secondaryButtonText: { fontSize: 15, fontWeight: '600', color: '#333' },
});
