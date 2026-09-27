import { useCallback, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import { ApiError, getRecommendations, NearbyTrail, RecommendationItem, trailsNear } from '../../src/api';
import { getCurrentLocation } from '../../src/location';

type ResultItem = RecommendationItem | NearbyTrail;

function isRecommendation(item: ResultItem): item is RecommendationItem {
  return 'because_you_liked_osm_id' in item;
}

export default function ExploreScreen() {
  const [items, setItems] = useState<ResultItem[]>([]);
  const [mode, setMode] = useState<'recommended' | 'nearby' | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // refetches every time this tab becomes focused, not just on first mount --
  // liking a trail on the detail screen and coming back here should be able
  // to flip this from the "nearby" fallback into real recommendations
  useFocusEffect(
    useCallback(() => {
      let cancelled = false;

      (async () => {
        setLoading(true);
        setError(null);
        try {
          const recs = await getRecommendations(20);
          if (!cancelled) {
            setItems(recs);
            setMode('recommended');
          }
        } catch (err) {
          if (err instanceof ApiError && err.status === 400) {
            // no liked trails yet -- fall back to what's near the user right now
            try {
              const location = await getCurrentLocation();
              const nearby = await trailsNear(location.lat, location.lon, { radiusKm: 50, limit: 20 });
              if (!cancelled) {
                setItems(nearby);
                setMode('nearby');
              }
            } catch (locErr) {
              if (!cancelled) setError(String(locErr));
            }
          } else if (!cancelled) {
            setError(String(err));
          }
        } finally {
          if (!cancelled) setLoading(false);
        }
      })();

      return () => {
        cancelled = true;
      };
    }, [])
  );

  return (
    <View style={styles.container}>
      {mode === 'recommended' && (
        <Text style={styles.subtitle}>Recommended based on trails you&apos;ve liked</Text>
      )}
      {mode === 'nearby' && (
        <Text style={styles.subtitle}>
          Like a few trails to get personalized picks — for now, here&apos;s what&apos;s near you
        </Text>
      )}

      {loading && <ActivityIndicator style={styles.spinner} />}
      {error && <Text style={styles.error}>{error}</Text>}

      <FlatList
        style={styles.list}
        data={items}
        keyExtractor={(item) => String(item.osm_id)}
        renderItem={({ item }) => (
          <Pressable style={styles.row} onPress={() => router.push(`/trail/${item.osm_id}`)}>
            <Text style={styles.name}>{item.name}</Text>
            <Text style={styles.meta}>
              {(item.distance_m / 1000).toFixed(1)} km · {Math.round(item.elevation_gain_m)} m gain ·{' '}
              {item.biome_name}
              {isRecommendation(item)
                ? ''
                : ` · ${item.distance_km.toFixed(1)} km away`}
            </Text>
          </Pressable>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff', paddingTop: 16, paddingHorizontal: 16 },
  subtitle: { fontSize: 13, color: '#666', marginBottom: 12 },
  spinner: { marginTop: 8 },
  error: { color: 'red', marginBottom: 12 },
  list: { flex: 1 },
  row: { paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#ddd' },
  name: { fontSize: 16, fontWeight: '600' },
  meta: { fontSize: 13, color: '#666', marginTop: 2 },
});
