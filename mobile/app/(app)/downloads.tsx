import { useCallback, useState } from 'react';
import { Alert, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import { FontAwesome } from '@expo/vector-icons';
import { hikeDistanceM, metersToFeet, metersToMiles } from '../../src/format';
import { listOfflineTrails, OfflineTrail, removeOfflineTrail } from '../../src/offlineTrails';
import { colors } from '../../src/theme';

type Row = { osmId: number; trail: OfflineTrail };

export default function DownloadsScreen() {
  const [rows, setRows] = useState<Row[]>([]);

  // re-reads from disk on focus -- a trail downloaded or removed from the
  // Trail Details screen should show up here without needing an app restart
  useFocusEffect(
    useCallback(() => {
      setRows(listOfflineTrails());
    }, [])
  );

  const confirmRemove = (row: Row) => {
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

  return (
    <View style={styles.container}>
      {rows.length === 0 ? (
        <View style={styles.center}>
          <Text style={styles.emptyText}>
            No trails downloaded yet — download one from its trail details screen to hike it offline.
          </Text>
        </View>
      ) : (
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
                  mi · {Math.round(metersToFeet(item.trail.detail.elevation_gain_m))} ft gain
                </Text>
              </Pressable>
              <Pressable style={styles.removeButton} hitSlop={12} onPress={() => confirmRemove(item)}>
                <FontAwesome name="trash-o" size={20} color={colors.textMuted} />
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
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  rowInfo: { flex: 1, paddingVertical: 10 },
  removeButton: { paddingLeft: 12, paddingVertical: 10 },
  name: { fontSize: 16, fontWeight: '600', color: colors.text },
  meta: { fontSize: 13, color: colors.textSecondary, marginTop: 2 },
});
