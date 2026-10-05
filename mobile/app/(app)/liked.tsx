import { useCallback, useState } from 'react';
import { ActivityIndicator, Alert, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import { FontAwesome } from '@expo/vector-icons';
import { listLikedTrails, TrailSummary, unlikeTrail } from '../../src/api';
import { hikeDistanceM, hikeElevationGainM, metersToFeet, metersToMiles } from '../../src/format';
import { listOfflineTrails, OfflineTrail, removeOfflineTrail } from '../../src/offlineTrails';
import { colors } from '../../src/theme';

type Section = 'liked' | 'downloaded';

export default function LikedScreen() {
  const [section, setSection] = useState<Section>('liked');

  return (
    <View style={styles.container}>
      <View style={styles.segmentedControl}>
        <Pressable
          style={[styles.segment, section === 'liked' && styles.segmentActive]}
          onPress={() => setSection('liked')}
        >
          <Text style={[styles.segmentText, section === 'liked' && styles.segmentTextActive]}>Liked</Text>
        </Pressable>
        <Pressable
          style={[styles.segment, section === 'downloaded' && styles.segmentActive]}
          onPress={() => setSection('downloaded')}
        >
          <Text style={[styles.segmentText, section === 'downloaded' && styles.segmentTextActive]}>
            Downloaded
          </Text>
        </Pressable>
      </View>

      {section === 'liked' ? <LikedList /> : <DownloadedList />}
    </View>
  );
}

function LikedList() {
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

  if (trails.length === 0) {
    return (
      <View style={styles.center}>
        <Text style={styles.emptyText}>No liked trails yet — find some in Search or Explore.</Text>
      </View>
    );
  }

  return (
    <FlatList
      style={styles.list}
      data={trails}
      keyExtractor={(item) => String(item.osm_id)}
      renderItem={({ item }) => (
        <View style={styles.row}>
          <Pressable style={styles.rowInfo} onPress={() => router.push(`/trail/${item.osm_id}`)}>
            <Text style={styles.name}>{item.name}</Text>
            <Text style={styles.meta}>
              {(hikeDistanceM(item.distance_m, item.is_loop) / 1000).toFixed(1)} km ·{' '}
              {Math.round(hikeElevationGainM(item.elevation_gain_m, item.elevation_loss_m, item.is_loop))} m
              gain · {item.biome_name}
            </Text>
          </Pressable>
          <Pressable style={styles.actionButton} onPress={() => handleUnlike(item.osm_id)} hitSlop={8}>
            <FontAwesome name="heart" size={22} color={colors.maroonLight} />
          </Pressable>
        </View>
      )}
    />
  );
}

type DownloadRow = { osmId: number; trail: OfflineTrail };

function DownloadedList() {
  const [rows, setRows] = useState<DownloadRow[]>([]);

  // re-reads from disk on focus -- a trail downloaded or removed from the
  // Trail Details screen should show up here without needing an app restart
  useFocusEffect(
    useCallback(() => {
      setRows(listOfflineTrails());
    }, [])
  );

  const confirmRemove = (row: DownloadRow) => {
    Alert.alert(
      'Remove downloaded trail?',
      `${row.trail.detail.name} will no longer be available offline. You can download it again anytime.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Remove',
          style: 'destructive',
          onPress: () => {
            removeOfflineTrail(row.osmId);
            setRows((current) => current.filter((r) => r.osmId !== row.osmId));
          },
        },
      ]
    );
  };

  if (rows.length === 0) {
    return (
      <View style={styles.center}>
        <Text style={styles.emptyText}>
          No trails downloaded yet — download one from its trail details screen to hike it offline.
        </Text>
      </View>
    );
  }

  return (
    <FlatList
      style={styles.list}
      data={rows}
      keyExtractor={(row) => String(row.osmId)}
      renderItem={({ item }) => (
        <View style={styles.row}>
          <Pressable style={styles.rowInfo} onPress={() => router.push(`/trail/${item.osmId}`)}>
            <Text style={styles.name}>{item.trail.detail.name}</Text>
            <Text style={styles.meta}>
              {metersToMiles(hikeDistanceM(item.trail.detail.distance_m, item.trail.detail.is_loop)).toFixed(2)}{' '}
              mi ·{' '}
              {Math.round(
                metersToFeet(
                  hikeElevationGainM(
                    item.trail.detail.elevation_gain_m,
                    item.trail.detail.elevation_loss_m,
                    item.trail.detail.is_loop
                  )
                )
              )}{' '}
              ft gain
            </Text>
          </Pressable>
          <Pressable style={styles.actionButton} hitSlop={12} onPress={() => confirmRemove(item)}>
            <FontAwesome name="trash-o" size={20} color={colors.textMuted} />
          </Pressable>
        </View>
      )}
    />
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, paddingTop: 16, paddingHorizontal: 16 },
  segmentedControl: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    borderRadius: 10,
    padding: 4,
    marginBottom: 16,
  },
  segment: { flex: 1, paddingVertical: 8, borderRadius: 8, alignItems: 'center' },
  segmentActive: { backgroundColor: colors.maroon },
  segmentText: { fontSize: 14, fontWeight: '600', color: colors.textSecondary },
  segmentTextActive: { color: colors.white },
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
  actionButton: { paddingLeft: 12, paddingVertical: 4 },
  name: { fontSize: 16, fontWeight: '600', color: colors.text },
  meta: { fontSize: 13, color: colors.textSecondary, marginTop: 2 },
});
