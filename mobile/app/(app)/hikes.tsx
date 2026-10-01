import { useCallback, useState } from 'react';
import { ActivityIndicator, Alert, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import { FontAwesome } from '@expo/vector-icons';
import { deleteHike, Hike, likeTrail, listHikes, listLikedTrails, unlikeTrail } from '../../src/api';
import { formatElapsed, formatPace, metersToMiles } from '../../src/format';
import { getOfflineTrail } from '../../src/offlineTrails';
import { listPendingHikes, PendingHike, removePendingHike, syncPendingHikes } from '../../src/pendingHikes';
import { colors } from '../../src/theme';

function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

type Row = { kind: 'synced'; hike: Hike } | { kind: 'pending'; hike: PendingHike };

export default function HikesScreen() {
  const [hikes, setHikes] = useState<Hike[]>([]);
  const [pending, setPending] = useState<PendingHike[]>([]);
  const [likedOsmIds, setLikedOsmIds] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(true);

  // refetches on focus, same as Liked/Explore -- a hike logged from Active
  // Hike should show up here without needing an app restart. syncing first
  // means a hike that finished offline and is now back in range gets moved
  // from "pending" to real history before the lists below are even fetched.
  useFocusEffect(
    useCallback(() => {
      let cancelled = false;

      syncPendingHikes()
        .catch(() => {})
        .then(() => Promise.all([listHikes(), listLikedTrails()]))
        .then((result) => {
          if (cancelled || !result) return;
          const [hikeResults, liked] = result;
          setHikes(hikeResults);
          setLikedOsmIds(new Set(liked.map((t) => t.osm_id)));
          setPending(listPendingHikes());
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

  const toggleLike = async (osmId: number) => {
    const isLiked = likedOsmIds.has(osmId);
    // optimistic, same as the Liked tab -- flip the heart immediately rather
    // than waiting on the network before reflecting the tap
    setLikedOsmIds((current) => {
      const next = new Set(current);
      if (isLiked) {
        next.delete(osmId);
      } else {
        next.add(osmId);
      }
      return next;
    });
    try {
      if (isLiked) {
        await unlikeTrail(osmId);
      } else {
        await likeTrail(osmId);
      }
    } catch {
      Alert.alert('Couldn’t update', 'Please check your connection and try again.');
      // revert on failure
      setLikedOsmIds((current) => {
        const next = new Set(current);
        if (isLiked) {
          next.add(osmId);
        } else {
          next.delete(osmId);
        }
        return next;
      });
    }
  };

  const confirmDelete = (hike: Hike) => {
    Alert.alert(
      'Delete this hike?',
      `${hike.trail_name ?? 'This hike'} — ${metersToMiles(hike.distance_m).toFixed(2)} mi on ${formatDate(hike.completed_at)}. This can't be undone.`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: () => handleDelete(hike.id) },
      ]
    );
  };

  const handleDelete = async (id: number) => {
    // optimistic, same pattern as the like toggle -- remove immediately,
    // restore it if the request actually fails
    const previous = hikes;
    setHikes((current) => current.filter((h) => h.id !== id));
    try {
      await deleteHike(id);
    } catch {
      Alert.alert('Couldn’t delete', 'Please check your connection and try again.');
      setHikes(previous);
    }
  };

  const confirmDeletePending = (hike: PendingHike) => {
    Alert.alert(
      'Discard this hike?',
      `${metersToMiles(hike.distanceM).toFixed(2)} mi, not yet synced. This can't be undone.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Discard',
          style: 'destructive',
          onPress: () => {
            removePendingHike(hike.id);
            setPending((current) => current.filter((h) => h.id !== hike.id));
          },
        },
      ]
    );
  };

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.maroonLight} />
      </View>
    );
  }

  // pending hikes surface first -- they're the ones that need attention
  // (and chronologically, they're usually the most recent anyway, since
  // they only exist because the most recent finish couldn't reach the
  // backend yet)
  const rows: Row[] = [
    ...pending.map((hike): Row => ({ kind: 'pending', hike })),
    ...hikes.map((hike): Row => ({ kind: 'synced', hike })),
  ];

  return (
    <View style={styles.container}>
      {rows.length === 0 ? (
        <View style={styles.center}>
          <Text style={styles.emptyText}>No completed hikes yet — finish one from Active Hike.</Text>
        </View>
      ) : (
        <FlatList
          style={styles.list}
          data={rows}
          keyExtractor={(row) => (row.kind === 'synced' ? `s${row.hike.id}` : `p${row.hike.id}`)}
          renderItem={({ item }) => {
            if (item.kind === 'pending') {
              const hike = item.hike;
              const offlineName = hike.osmId !== null ? getOfflineTrail(hike.osmId)?.detail.name : null;
              return (
                <View style={styles.row}>
                  <View style={styles.rowInfo}>
                    <View style={styles.pendingHeader}>
                      <Text style={styles.name}>{offlineName ?? 'Pending hike'}</Text>
                      <Text style={styles.pendingBadge}>PENDING SYNC</Text>
                    </View>
                    <Text style={styles.meta}>
                      {formatDate(hike.queuedAt)} · {metersToMiles(hike.distanceM).toFixed(2)} mi ·{' '}
                      {formatElapsed(hike.movingTimeS * 1000)} ·{' '}
                      {formatPace(hike.movingTimeS * 1000, hike.distanceM)}
                    </Text>
                  </View>
                  <Pressable style={styles.deleteButton} hitSlop={12} onPress={() => confirmDeletePending(hike)}>
                    <FontAwesome name="trash-o" size={20} color={colors.textMuted} />
                  </Pressable>
                </View>
              );
            }

            const hike = item.hike;
            return (
              <View style={styles.row}>
                <Pressable
                  style={styles.rowInfo}
                  disabled={hike.osm_id === null}
                  onPress={() => router.push(`/trail/${hike.osm_id}`)}
                >
                  <Text style={styles.name}>{hike.trail_name ?? 'Unknown trail'}</Text>
                  <Text style={styles.meta}>
                    {formatDate(hike.completed_at)} · {metersToMiles(hike.distance_m).toFixed(2)} mi ·{' '}
                    {formatElapsed(hike.moving_time_s * 1000)} ·{' '}
                    {formatPace(hike.moving_time_s * 1000, hike.distance_m)}
                  </Text>
                </Pressable>
                {hike.osm_id !== null && (
                  <Pressable style={styles.likeButton} hitSlop={12} onPress={() => toggleLike(hike.osm_id!)}>
                    <FontAwesome
                      name={likedOsmIds.has(hike.osm_id) ? 'heart' : 'heart-o'}
                      size={20}
                      color={likedOsmIds.has(hike.osm_id) ? colors.maroonLight : colors.textMuted}
                    />
                  </Pressable>
                )}
                <Pressable style={styles.deleteButton} hitSlop={12} onPress={() => confirmDelete(hike)}>
                  <FontAwesome name="trash-o" size={20} color={colors.textMuted} />
                </Pressable>
              </View>
            );
          }}
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
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  rowInfo: { flex: 1, paddingVertical: 10 },
  likeButton: { paddingLeft: 12, paddingVertical: 10 },
  deleteButton: { paddingLeft: 12, paddingVertical: 10 },
  name: { fontSize: 16, fontWeight: '600', color: colors.text },
  meta: { fontSize: 13, color: colors.textSecondary, marginTop: 2 },
  pendingHeader: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  pendingBadge: {
    fontSize: 10,
    fontWeight: '700',
    color: colors.white,
    backgroundColor: colors.warning,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
});
