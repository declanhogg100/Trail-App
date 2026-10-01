import { useCallback, useState } from 'react';
import { ActivityIndicator, Alert, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import { FontAwesome } from '@expo/vector-icons';
import { listLikedTrails, TrailSummary, unlikeTrail } from '../../src/api';
import { colors } from '../../src/theme';

export default function LikedScreen() {
  const [trails, setTrails] = useState<TrailSummary[]>([]);
  const [loading, setLoading] = useState(true);

  // refetches every time this tab becomes focused -- liking a trail from the
  // detail screen should show up here without needing an app restart
  useFocusEffect(
    useCallback(() => {
      let cancelled = false;

      listLikedTrails()
        .then((liked) => {
          if (!cancelled) setTrails(liked);
        })
        .catch(() => {})
        .finally(() => {
          if (!cancelled) setLoading(false);
        });

      return () => {
        cancelled = true;
      };
    }, [])
  );

  const handleUnlike = async (osmId: number) => {
    // optimistic: remove from the list immediately, since this screen's
    // whole purpose is showing liked trails -- no reason to wait on the
    // network before reflecting the unlike
    setTrails((current) => current.filter((t) => t.osm_id !== osmId));
    try {
      await unlikeTrail(osmId);
    } catch {
      Alert.alert('Couldn’t update', 'Please check your connection and try again.');
    }
  };

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.maroonLight} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {trails.length === 0 ? (
        <View style={styles.center}>
          <Text style={styles.emptyText}>
            No liked trails yet — find some in Search or Explore.
          </Text>
        </View>
      ) : (
        <FlatList
          style={styles.list}
          data={trails}
          keyExtractor={(item) => String(item.osm_id)}
          renderItem={({ item }) => (
            <View style={styles.row}>
              <Pressable style={styles.rowInfo} onPress={() => router.push(`/trail/${item.osm_id}`)}>
                <Text style={styles.name}>{item.name}</Text>
                <Text style={styles.meta}>
                  {(item.distance_m / 1000).toFixed(1)} km · {Math.round(item.elevation_gain_m)} m gain ·{' '}
                  {item.biome_name}
                </Text>
              </Pressable>
              <Pressable
                style={styles.heartButton}
                onPress={() => handleUnlike(item.osm_id)}
                hitSlop={8}
              >
                <FontAwesome name="heart" size={22} color={colors.maroonLight} />
              </Pressable>
            </View>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, paddingTop: 16, paddingHorizontal: 16 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 32 },
  emptyText: { fontSize: 15, color: colors.textMuted, textAlign: 'center' },
  list: { flex: 1 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  rowInfo: { flex: 1 },
  name: { fontSize: 16, fontWeight: '600', color: colors.text },
  meta: { fontSize: 13, color: colors.textSecondary, marginTop: 2 },
  heartButton: { paddingLeft: 12, paddingVertical: 4 },
});
