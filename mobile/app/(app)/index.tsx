import { useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  SectionList,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { router } from 'expo-router';
import { listTrails, trailsNear, NearbyTrail, TrailSummary } from '../../src/api';
import { geocodeArea } from '../../src/location';

type ResultItem = TrailSummary | NearbyTrail;

function isNearby(item: ResultItem): item is NearbyTrail {
  return 'distance_km' in item;
}

export default function SearchScreen() {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [geocodeNote, setGeocodeNote] = useState<string | null>(null);
  const [nameMatches, setNameMatches] = useState<TrailSummary[]>([]);
  const [areaMatches, setAreaMatches] = useState<NearbyTrail[]>([]);
  const [areaLabel, setAreaLabel] = useState<string | null>(null);

  const runSearch = async () => {
    const trimmed = query.trim();
    if (!trimmed) return;

    setLoading(true);
    setError(null);
    setGeocodeNote(null);
    setAreaLabel(null);

    try {
      const nameResult = await listTrails({ search: trimmed, limit: 20 });
      setNameMatches(nameResult.trails);

      // geocoding failing (no permission, no network, unrecognized place
      // name) shouldn't block the name-match results above -- area search
      // is a bonus on top, not a requirement
      let location: { lat: number; lon: number } | null = null;
      try {
        location = await geocodeArea(trimmed);
      } catch (err) {
        setGeocodeNote(String(err));
      }

      if (location) {
        const nearby = await trailsNear(location.lat, location.lon, { radiusKm: 50, limit: 20 });
        setAreaMatches(nearby);
        setAreaLabel(trimmed);
      } else {
        setAreaMatches([]);
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  const sections = [
    ...(nameMatches.length > 0 ? [{ title: 'Matching trails', data: nameMatches as ResultItem[] }] : []),
    ...(areaLabel ? [{ title: `Near "${areaLabel}"`, data: areaMatches as ResultItem[] }] : []),
  ];

  return (
    <View style={styles.container}>
      <TextInput
        style={styles.input}
        placeholder="Search a trail name or area (e.g. Yosemite)"
        value={query}
        onChangeText={setQuery}
        onSubmitEditing={runSearch}
        returnKeyType="search"
      />

      {loading && <ActivityIndicator style={styles.spinner} />}
      {error && <Text style={styles.error}>{error}</Text>}
      {geocodeNote && <Text style={styles.hint}>{geocodeNote}</Text>}
      {!loading && areaLabel && areaMatches.length === 0 && (
        <Text style={styles.hint}>No trails found near &quot;{areaLabel}&quot; in the catalog.</Text>
      )}

      <SectionList
        style={styles.list}
        sections={sections}
        keyExtractor={(item) => String(item.osm_id)}
        renderSectionHeader={({ section }) => <Text style={styles.sectionHeader}>{section.title}</Text>}
        renderItem={({ item }) => (
          <Pressable style={styles.row} onPress={() => router.push(`/trail/${item.osm_id}`)}>
            <Text style={styles.name}>{item.name}</Text>
            <Text style={styles.meta}>
              {(item.distance_m / 1000).toFixed(1)} km · {Math.round(item.elevation_gain_m)} m gain ·{' '}
              {item.biome_name}
              {isNearby(item) ? ` · ${item.distance_km.toFixed(1)} km away` : ''}
            </Text>
          </Pressable>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff', paddingTop: 16, paddingHorizontal: 16 },
  input: {
    borderWidth: 1,
    borderColor: '#ccc',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 16,
    marginBottom: 12,
  },
  spinner: { marginTop: 8 },
  error: { color: 'red', marginBottom: 12 },
  hint: { color: '#999', fontSize: 13, marginBottom: 12 },
  list: { flex: 1 },
  sectionHeader: {
    fontSize: 13,
    fontWeight: '700',
    color: '#666',
    backgroundColor: '#fff',
    paddingTop: 8,
    paddingBottom: 4,
  },
  row: { paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#ddd' },
  name: { fontSize: 16, fontWeight: '600' },
  meta: { fontSize: 13, color: '#666', marginTop: 2 },
});
