import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Platform,
  Pressable,
  ScrollView,
  SectionList,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { FontAwesome } from '@expo/vector-icons';
import { AppleMaps, GoogleMaps } from 'expo-maps';
import {
  getTrailGeometry,
  listTrails,
  trailsInBounds,
  trailsNear,
  NearbyTrail,
  TrailMapMarker,
  TrailSummary,
} from '../../src/api';
import { hikeDistanceM, hikeElevationGainM } from '../../src/format';
import { geocodeArea, getCurrentLocation } from '../../src/location';
import { TrailDetailContent } from '../../src/components/TrailDetailContent';
import { colors } from '../../src/theme';

// continental US, zoomed out enough to see the whole country on first open
const INITIAL_CAMERA = {
  coordinates: { latitude: 39.5, longitude: -98.35 },
  zoom: 3.7,
};

const TRAIL_COLOR = '#2e7d32';
const TRAIL_WIDTH = 4;
// neither AppleMaps.View nor GoogleMaps.View expose a native outline/casing
// property on a polyline -- a faint halo is faked by drawing a wider,
// translucent line of the same color underneath the real one
const TRAIL_OUTLINE_COLOR = 'rgba(46, 125, 50, 0.35)';
const TRAIL_OUTLINE_WIDTH = 8;
const DEBOUNCE_MS = 400;
// below this zoom level (larger visible area), don't show trails at all --
// a fully zoomed-out view has way too many candidate trails to usefully
// show as individual markers, so the map stays empty until you zoom in
// close enough for markers to mean something (roughly a multi-county area)
const MAX_LONGITUDE_DELTA_TO_SHOW = 4;

// when a trail is selected, the camera zooms to fit its whole route -- but
// capped at this span so a multi-state trail (the PCT spans three) doesn't
// zoom all the way back out to a barely-useful regional view. A trail that
// doesn't fit gets centered on the point that was tapped instead, showing
// local detail there rather than an arbitrary faraway part of the route
const MAX_SELECTED_SPAN_DEG = 1.5;
const MIN_SELECTED_SPAN_DEG = 0.02;
const SELECTED_SPAN_PADDING = 1.4;

// roughly 10km across (~5km out in every direction) -- the default view once
// the device's location comes back, instead of staying zoomed out to the
// whole-country INITIAL_CAMERA
const NEARBY_SPAN_DEG = 0.09;

type Bounds = { minLon: number; minLat: number; maxLon: number; maxLat: number };
type ResultItem = TrailSummary | NearbyTrail;
type SelectedTrail = { osmId: number; lines: [number, number][][]; start: [number, number] };
// AppleMaps.View and GoogleMaps.View both expose the same setCameraPosition
// shape on their ref -- Platform.OS picks which one actually renders, so a
// union covers whichever is live without needing two separate ref vars
type MapRef = AppleMaps.MapView | GoogleMaps.MapView;

function isNearby(item: ResultItem): item is NearbyTrail {
  return 'distance_km' in item;
}

function boundsFromCamera(latitude: number, longitude: number, latitudeDelta: number, longitudeDelta: number): Bounds {
  return {
    minLon: longitude - longitudeDelta / 2,
    maxLon: longitude + longitudeDelta / 2,
    minLat: latitude - latitudeDelta / 2,
    maxLat: latitude + latitudeDelta / 2,
  };
}

function bboxFromLines(lines: [number, number][][]) {
  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;
  for (const line of lines) {
    for (const [lon, lat] of line) {
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
  }
  return { minLon, minLat, maxLon, maxLat };
}

// approximates the standard slippy-map zoom convention (span halves each
// zoom level) -- not pixel-perfect since it ignores screen width, but close
// enough for a "zoom to roughly fit this span" heuristic
function zoomForSpan(spanDeg: number): number {
  return Math.log2(360 / spanDeg) + 1;
}

export default function SearchScreen() {
  // --- map state ---
  const mapRef = useRef<MapRef>(null);
  const [markers, setMarkers] = useState<TrailMapMarker[]>([]);
  const [mapLoading, setMapLoading] = useState(false);
  const [zoomedOutTooFar, setZoomedOutTooFar] = useState(false);
  const [selectedTrail, setSelectedTrail] = useState<SelectedTrail | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastBoundsRef = useRef<Bounds | null>(null);
  // the native map view's gesture recognizers aren't necessarily ready the
  // instant this component mounts -- an imperative setCameraPosition() call
  // before then can leave pinch/pan gestures unresponsive. These track
  // whichever of "map ready" (first onCameraMove firing) / "location fixed"
  // arrives second, so the initial zoom-to-location only ever fires once the
  // map itself confirms it's actually ready for it.
  const mapReadyRef = useRef(false);
  const userLocationRef = useRef<{ lat: number; lon: number } | null>(null);
  const initialZoomDoneRef = useRef(false);

  // --- search overlay state ---
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [searchLoading, setSearchLoading] = useState(false);
  const [nameMatches, setNameMatches] = useState<TrailSummary[]>([]);
  const [areaMatches, setAreaMatches] = useState<NearbyTrail[]>([]);
  const [areaLabel, setAreaLabel] = useState<string | null>(null);

  const fetchMarkers = useCallback((bounds: Bounds) => {
    lastBoundsRef.current = bounds;
    setMapLoading(true);
    trailsInBounds(bounds)
      .then((results) => {
        // a slower-arriving response for a bbox the user has since panned
        // away from would otherwise flash in and overwrite newer trails
        if (lastBoundsRef.current === bounds) setMarkers(results);
      })
      .catch(() => {})
      .finally(() => {
        if (lastBoundsRef.current === bounds) setMapLoading(false);
      });
  }, []);

  // zooms in on the device's current location as soon as both the location
  // fix and the map itself are ready -- without this the map opens on
  // INITIAL_CAMERA's whole-country view, which isn't useful until you
  // manually pan/zoom to wherever you actually are
  const maybeApplyInitialZoom = useCallback(() => {
    if (initialZoomDoneRef.current || !mapReadyRef.current || !userLocationRef.current) return;
    initialZoomDoneRef.current = true;
    const { lat, lon } = userLocationRef.current;
    mapRef.current?.setCameraPosition({
      coordinates: { latitude: lat, longitude: lon },
      zoom: zoomForSpan(NEARBY_SPAN_DEG),
    });
    fetchMarkers({
      minLon: lon - NEARBY_SPAN_DEG / 2,
      maxLon: lon + NEARBY_SPAN_DEG / 2,
      minLat: lat - NEARBY_SPAN_DEG / 2,
      maxLat: lat + NEARBY_SPAN_DEG / 2,
    });
  }, [fetchMarkers]);

  useEffect(() => {
    getCurrentLocation()
      .then(({ lat, lon }) => {
        userLocationRef.current = { lat, lon };
        maybeApplyInitialZoom();
      })
      .catch(() => {
        // no permission or no fix -- just stay on the zoomed-out default
        // rather than blocking the map on a location prompt
      });
  }, [maybeApplyInitialZoom]);

  const handleCameraMove = useCallback(
    (event: { coordinates: { latitude?: number; longitude?: number }; latitudeDelta: number; longitudeDelta: number }) => {
      // AppleMaps.View fires onCameraMove once on initial mount with the
      // starting viewport, before any gesture -- the first call is this
      // component's only reliable "the native view is ready" signal
      if (!mapReadyRef.current) {
        mapReadyRef.current = true;
        maybeApplyInitialZoom();
      }

      const { latitude, longitude } = event.coordinates;
      if (latitude === undefined || longitude === undefined) return;

      if (event.longitudeDelta > MAX_LONGITUDE_DELTA_TO_SHOW) {
        setZoomedOutTooFar(true);
        setMarkers([]);
        lastBoundsRef.current = null;
        if (debounceRef.current) clearTimeout(debounceRef.current);
        return;
      }
      setZoomedOutTooFar(false);

      const bounds = boundsFromCamera(latitude, longitude, event.latitudeDelta, event.longitudeDelta);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => fetchMarkers(bounds), DEBOUNCE_MS);
    },
    [fetchMarkers, maybeApplyInitialZoom]
  );

  // fetches a trail's route, zooms the camera to fit it (capped), and opens
  // the details sheet -- the one path both a map marker tap and a search
  // result tap funnel into
  const selectTrail = useCallback(
    (osmId: number) => {
      getTrailGeometry(osmId)
        .then((geometry) => {
          const bbox = bboxFromLines(geometry.lines);
          const rawSpan = Math.max(bbox.maxLon - bbox.minLon, bbox.maxLat - bbox.minLat);
          const paddedSpan = rawSpan * SELECTED_SPAN_PADDING;
          const fitsFully = paddedSpan <= MAX_SELECTED_SPAN_DEG;
          const cappedSpan = Math.min(Math.max(paddedSpan, MIN_SELECTED_SPAN_DEG), MAX_SELECTED_SPAN_DEG);

          const [startLon, startLat] = geometry.lines[0][0];
          const center = fitsFully
            ? { latitude: (bbox.minLat + bbox.maxLat) / 2, longitude: (bbox.minLon + bbox.maxLon) / 2 }
            : { latitude: startLat, longitude: startLon };

          mapRef.current?.setCameraPosition({ coordinates: center, zoom: zoomForSpan(cappedSpan) });
          setSelectedTrail({ osmId, lines: geometry.lines, start: [startLon, startLat] });
          setSearchOpen(false);

          // markers refresh around the new center right away, so if the
          // sheet is closed immediately after, the pins already match the
          // new camera position instead of showing stale ones from before
          fetchMarkers({
            minLon: center.longitude - cappedSpan / 2,
            maxLon: center.longitude + cappedSpan / 2,
            minLat: center.latitude - cappedSpan / 2,
            maxLat: center.latitude + cappedSpan / 2,
          });
        })
        .catch(() => {});
    },
    [fetchMarkers]
  );

  const handleMarkerClick = useCallback(
    (marker: { id?: string }) => {
      if (marker.id) selectTrail(Number(marker.id));
    },
    [selectTrail]
  );

  const runSearch = async () => {
    const trimmed = query.trim();
    if (!trimmed) return;

    setSearchLoading(true);
    setAreaLabel(null);

    try {
      const nameResult = await listTrails({ search: trimmed, limit: 20 });
      setNameMatches(nameResult.trails);

      // geocoding failing (no permission, no network, unrecognized place
      // name) shouldn't block the name-match results above -- area search
      // is a bonus on top, not a requirement, so a failure here is silent
      let location: { lat: number; lon: number } | null = null;
      try {
        location = await geocodeArea(trimmed);
      } catch {
        // no-op -- see comment above
      }

      if (location) {
        const nearby = await trailsNear(location.lat, location.lon, { radiusKm: 50, limit: 20 });
        setAreaMatches(nearby);
        setAreaLabel(trimmed);
      } else {
        setAreaMatches([]);
      }
    } catch {
      Alert.alert('Search failed', 'Please check your connection and try again.');
    } finally {
      setSearchLoading(false);
    }
  };

  // while a trail is selected, hide every other pin -- only the selected
  // trail's own marker (and its route, via `polylines` below) stays visible
  // until the details sheet is closed
  const mapMarkers = selectedTrail
    ? [
        {
          coordinates: { latitude: selectedTrail.start[1], longitude: selectedTrail.start[0] },
          id: String(selectedTrail.osmId),
        },
      ]
    : markers.map((trail) => ({
        coordinates: { latitude: trail.start[1], longitude: trail.start[0] },
        title: trail.name,
        id: String(trail.osm_id),
      }));

  // the outline polylines are listed first so the real trail line draws on
  // top of them, not the other way around
  const polylines = selectedTrail
    ? [
        ...selectedTrail.lines.map((line) => ({
          coordinates: line.map(([lon, lat]) => ({ latitude: lat, longitude: lon })),
          color: TRAIL_OUTLINE_COLOR,
          width: TRAIL_OUTLINE_WIDTH,
        })),
        ...selectedTrail.lines.map((line) => ({
          coordinates: line.map(([lon, lat]) => ({ latitude: lat, longitude: lon })),
          color: TRAIL_COLOR,
          width: TRAIL_WIDTH,
        })),
      ]
    : [];

  const sections = [
    ...(nameMatches.length > 0 ? [{ title: 'Matching trails', data: nameMatches as ResultItem[] }] : []),
    ...(areaLabel && areaMatches.length > 0
      ? [{ title: `Near "${areaLabel}"`, data: areaMatches as ResultItem[] }]
      : []),
  ];

  return (
    <View style={styles.container}>
      {Platform.OS === 'ios' ? (
        <AppleMaps.View
          ref={mapRef as React.Ref<AppleMaps.MapView>}
          style={styles.map}
          cameraPosition={INITIAL_CAMERA}
          onCameraMove={handleCameraMove}
          polylines={polylines}
          markers={mapMarkers}
          onMarkerClick={handleMarkerClick}
          properties={{ isMyLocationEnabled: true }}
        />
      ) : (
        <GoogleMaps.View
          ref={mapRef as React.Ref<GoogleMaps.MapView>}
          style={styles.map}
          cameraPosition={INITIAL_CAMERA}
          onCameraMove={handleCameraMove}
          polylines={polylines}
          markers={mapMarkers}
          onMarkerClick={handleMarkerClick}
          properties={{ isMyLocationEnabled: true }}
        />
      )}

      {!searchOpen && !selectedTrail && (
        <Pressable style={styles.searchBar} onPress={() => setSearchOpen(true)}>
          <Text style={styles.searchBarText}>Search a trail name or area</Text>
        </Pressable>
      )}

      {!searchOpen && !selectedTrail && zoomedOutTooFar && (
        <View style={styles.hintBadge}>
          <Text style={styles.hintText}>Zoom in to see trails</Text>
        </View>
      )}
      {!searchOpen && mapLoading && (
        <View style={styles.loadingBadge}>
          <ActivityIndicator color={colors.maroonLight} />
        </View>
      )}

      {searchOpen && (
        <View style={styles.searchOverlay}>
          <View style={styles.searchHeader}>
            <Pressable style={styles.backButton} onPress={() => setSearchOpen(false)}>
              <FontAwesome name="arrow-left" size={20} color={colors.text} />
            </Pressable>
            <TextInput
              style={styles.input}
              placeholder="Search a trail name or area (e.g. Yosemite)"
              value={query}
              onChangeText={setQuery}
              onSubmitEditing={runSearch}
              returnKeyType="search"
              autoFocus
            />
          </View>

          {searchLoading && <ActivityIndicator style={styles.spinner} color={colors.maroonLight} />}

          <SectionList
            style={styles.list}
            sections={sections}
            keyExtractor={(item) => String(item.osm_id)}
            renderSectionHeader={({ section }) => <Text style={styles.sectionHeader}>{section.title}</Text>}
            renderItem={({ item }) => (
              <Pressable style={styles.row} onPress={() => selectTrail(item.osm_id)}>
                <Text style={styles.name}>{item.name}</Text>
                <Text style={styles.meta}>
                  {(hikeDistanceM(item.distance_m, item.is_loop) / 1000).toFixed(1)} km ·{' '}
                  {Math.round(hikeElevationGainM(item.elevation_gain_m, item.elevation_loss_m, item.is_loop))} m gain ·{' '}
                  {item.biome_name}
                  {isNearby(item) ? ` · ${item.distance_km.toFixed(1)} km away` : ''}
                </Text>
              </Pressable>
            )}
          />
        </View>
      )}

      {selectedTrail && (
        <View style={styles.detailSheet}>
          <View style={styles.detailHeader}>
            <View style={styles.dragHandle} />
            <Pressable style={styles.closeButton} onPress={() => setSelectedTrail(null)}>
              <FontAwesome name="times" size={20} color={colors.text} />
            </Pressable>
          </View>
          <ScrollView style={styles.detailScroll} contentContainerStyle={styles.detailContent}>
            <TrailDetailContent osmId={selectedTrail.osmId} />
          </ScrollView>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  map: { flex: 1 },
  searchBar: {
    position: 'absolute',
    top: 16,
    left: 16,
    right: 16,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: colors.surface,
    borderRadius: 24,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  searchBarText: { color: colors.textSecondary, fontSize: 15 },
  loadingBadge: {
    position: 'absolute',
    top: 16,
    right: 16,
    backgroundColor: colors.surface,
    borderRadius: 20,
    padding: 8,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  hintBadge: {
    position: 'absolute',
    top: 74,
    alignSelf: 'center',
    backgroundColor: colors.surface,
    borderRadius: 16,
    paddingVertical: 8,
    paddingHorizontal: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  hintText: { color: colors.text, fontSize: 13, fontWeight: '600' },
  searchOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: colors.background,
    paddingTop: 16,
    paddingHorizontal: 16,
  },
  searchHeader: { flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 12 },
  backButton: { padding: 4 },
  input: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 16,
    color: colors.text,
  },
  spinner: { marginTop: 8 },
  list: { flex: 1 },
  sectionHeader: {
    fontSize: 13,
    fontWeight: '700',
    color: colors.textSecondary,
    backgroundColor: colors.background,
    paddingTop: 8,
    paddingBottom: 4,
  },
  row: { paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: colors.border },
  name: { fontSize: 16, fontWeight: '600', color: colors.text },
  meta: { fontSize: 13, color: colors.textSecondary, marginTop: 2 },
  detailSheet: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    height: '50%',
    backgroundColor: colors.surface,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  // an explicit height here matters: closeButton is absolutely positioned
  // and its touch target (padding + icon) overflows past the drag handle's
  // own tiny content height. Without a height set here, detailScroll below
  // (a later sibling, so stacked on top wherever they overlap) would cover
  // that overflow and swallow taps meant for the button, even though the
  // icon still renders visibly through it.
  detailHeader: { height: 44, alignItems: 'center', paddingTop: 8 },
  dragHandle: { width: 36, height: 4, borderRadius: 2, backgroundColor: colors.border },
  closeButton: { position: 'absolute', right: 12, top: 4, padding: 8, zIndex: 1 },
  detailScroll: { flex: 1 },
  detailContent: { padding: 16, paddingTop: 8 },
});
