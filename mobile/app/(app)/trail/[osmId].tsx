import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { getTrail, likeTrail, listLikedTrails, TrailDetail, unlikeTrail } from '../../../src/api';
import { useActiveHike } from '../../../src/activeHike';

export default function TrailDetailScreen() {
  // params from the URL are always strings, even though osm_id is a number
  // everywhere else in the app -- convert once, right at the boundary
  const { osmId: osmIdParam } = useLocalSearchParams<{ osmId: string }>();
  const osmId = Number(osmIdParam);

  const [trail, setTrail] = useState<TrailDetail | null>(null);
  const [isLiked, setIsLiked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { status: hikeStatus, start: startHike } = useActiveHike();

  useEffect(() => {
    getTrail(osmId)
      .then(setTrail)
      .catch((err) => setError(String(err)));

    listLikedTrails()
      .then((liked) => setIsLiked(liked.some((t) => t.osm_id === osmId)))
      .catch((err) => setError(String(err)));
  }, [osmId]);

  const toggleLike = async () => {
    try {
      if (isLiked) {
        await unlikeTrail(osmId);
      } else {
        await likeTrail(osmId);
      }
      setIsLiked(!isLiked);
    } catch (err) {
      setError(String(err));
    }
  };

  const handleStartHike = async () => {
    // a hike's already running (possibly for a different trail) -- don't
    // silently overwrite it, just jump to the live tracking screen
    if (hikeStatus !== 'idle') {
      router.push('/active-hike');
      return;
    }
    try {
      await startHike(trail!.name, osmId);
      router.push('/active-hike');
    } catch (err) {
      setError(String(err));
    }
  };

  if (error) {
    return (
      <View style={styles.center}>
        <Text style={styles.error}>{error}</Text>
      </View>
    );
  }

  if (!trail) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Stack.Screen options={{ title: trail.name }} />

      <Text style={styles.title}>{trail.name}</Text>
      <Text style={styles.biome}>{trail.biome_name}</Text>

      <Pressable style={[styles.likeButton, isLiked && styles.likeButtonActive]} onPress={toggleLike}>
        <Text style={[styles.likeButtonText, isLiked && styles.likeButtonTextActive]}>
          {isLiked ? '♥ Liked' : '♡ Like this trail'}
        </Text>
      </Pressable>

      <Pressable style={styles.startHikeButton} onPress={handleStartHike}>
        <Text style={styles.startHikeButtonText}>
          {hikeStatus === 'idle' ? 'Start Hike' : 'Hike in progress — view'}
        </Text>
      </Pressable>

      <View style={styles.statsGrid}>
        <Stat label="Distance" value={`${(trail.distance_m / 1000).toFixed(1)} km`} />
        <Stat label="Elevation gain" value={`${Math.round(trail.elevation_gain_m)} m`} />
        <Stat label="Peak elevation" value={`${Math.round(trail.peak_elevation_m)} m`} />
        <Stat label="Peak prominence" value={`${Math.round(trail.peak_prominence_m)} m`} />
        <Stat label="Tree cover" value={`${Math.round(trail.tree_cover_pct)}%`} />
        <Stat label="Realm" value={trail.realm} />
      </View>

      <Text style={styles.ecoName}>{trail.eco_name}</Text>
    </ScrollView>
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
  container: { flex: 1, backgroundColor: '#fff' },
  content: { padding: 16 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  error: { color: 'red' },
  title: { fontSize: 24, fontWeight: '700' },
  biome: { fontSize: 15, color: '#666', marginTop: 4 },
  likeButton: {
    marginTop: 16,
    paddingVertical: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#333',
    alignItems: 'center',
  },
  likeButtonActive: { backgroundColor: '#333' },
  likeButtonText: { fontSize: 15, fontWeight: '600', color: '#333' },
  likeButtonTextActive: { color: '#fff' },
  startHikeButton: {
    marginTop: 12,
    paddingVertical: 12,
    borderRadius: 8,
    backgroundColor: '#2e7d32',
    alignItems: 'center',
  },
  startHikeButtonText: { fontSize: 16, fontWeight: '700', color: '#fff' },
  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 24, gap: 16 },
  stat: { width: '45%' },
  statValue: { fontSize: 18, fontWeight: '700' },
  statLabel: { fontSize: 13, color: '#666', marginTop: 2 },
  ecoName: { fontSize: 13, color: '#999', marginTop: 24, fontStyle: 'italic' },
});
