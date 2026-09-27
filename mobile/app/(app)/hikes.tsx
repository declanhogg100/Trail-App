import { useCallback, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import { Hike, listHikes } from '../../src/api';
import { formatElapsed, formatPace, metersToMiles } from '../../src/format';

function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

export default function HikesScreen() {
  const [hikes, setHikes] = useState<Hike[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // refetches on focus, same as Liked/Explore -- a hike logged from Active
  // Hike should show up here without needing an app restart
  useFocusEffect(
    useCallback(() => {
      let cancelled = false;

      listHikes()
        .then((data) => {
          if (!cancelled) setHikes(data);
        })
        .catch((err) => {
          if (!cancelled) setError(String(err));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });

      return () => {
        cancelled = true;
      };
    }, [])
  );

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {error && <Text style={styles.error}>{error}</Text>}

      {hikes.length === 0 ? (
        <View style={styles.center}>
          <Text style={styles.emptyText}>No completed hikes yet — finish one from Active Hike.</Text>
        </View>
      ) : (
        <FlatList
          style={styles.list}
          data={hikes}
          keyExtractor={(item) => String(item.id)}
          renderItem={({ item }) => (
            <Pressable
              style={styles.row}
              disabled={item.osm_id === null}
              onPress={() => router.push(`/trail/${item.osm_id}`)}
            >
              <Text style={styles.name}>{item.trail_name ?? 'Unknown trail'}</Text>
              <Text style={styles.meta}>
                {formatDate(item.completed_at)} · {metersToMiles(item.distance_m).toFixed(2)} mi ·{' '}
                {formatElapsed(item.moving_time_s * 1000)} ·{' '}
                {formatPace(item.moving_time_s * 1000, item.distance_m)}
              </Text>
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff', paddingTop: 16, paddingHorizontal: 16 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 32 },
  emptyText: { fontSize: 15, color: '#999', textAlign: 'center' },
  error: { color: 'red', marginBottom: 12 },
  list: { flex: 1 },
  row: { paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#ddd' },
  name: { fontSize: 16, fontWeight: '600' },
  meta: { fontSize: 13, color: '#666', marginTop: 2 },
});
