import { useState } from 'react';
import { ScrollView, StyleSheet } from 'react-native';
import { Stack, useLocalSearchParams } from 'expo-router';
import { TrailDetailContent } from '../../../src/components/TrailDetailContent';

export default function TrailDetailScreen() {
  // params from the URL are always strings, even though osm_id is a number
  // everywhere else in the app -- convert once, right at the boundary
  const { osmId: osmIdParam } = useLocalSearchParams<{ osmId: string }>();
  const osmId = Number(osmIdParam);
  const [title, setTitle] = useState('');

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Stack.Screen options={{ title }} />
      <TrailDetailContent osmId={osmId} onLoaded={(trail) => setTitle(trail.name)} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  content: { padding: 16 },
});
