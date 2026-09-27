import * as Location from 'expo-location';
import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react';

type Status = 'idle' | 'active' | 'paused';

type ActiveHikeContextValue = {
  status: Status;
  trailName: string | null;
  distanceM: number;
  elevationGainM: number;
  elapsedMs: number;
  start: (trailName: string, osmId: number) => Promise<void>;
  pause: () => void;
  resume: () => Promise<void>;
  finish: () => { distanceM: number; elapsedS: number; osmId: number | null };
};

const ActiveHikeContext = createContext<ActiveHikeContextValue | null>(null);

const EARTH_RADIUS_M = 6371000;

function haversineMeters(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(a));
}

export function ActiveHikeProvider({ children }: PropsWithChildren) {
  const [status, setStatus] = useState<Status>('idle');
  const [trailName, setTrailName] = useState<string | null>(null);
  const [distanceM, setDistanceM] = useState(0);
  const [elevationGainM, setElevationGainM] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);

  // refs, not state -- these drive accumulation logic between renders but
  // don't themselves need to trigger a re-render when they change
  const lastPositionRef = useRef<{ lat: number; lon: number; altitude: number | null } | null>(
    null
  );
  const subscriptionRef = useRef<Location.LocationSubscription | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedAtRef = useRef<number>(0);
  const pausedAccumulatedMsRef = useRef<number>(0);
  const pausedAtRef = useRef<number>(0);
  const osmIdRef = useRef<number | null>(null);

  const onLocationUpdate = useCallback((location: Location.LocationObject) => {
    const { latitude, longitude, altitude } = location.coords;
    const last = lastPositionRef.current;

    if (last) {
      const stepDistance = haversineMeters(last.lat, last.lon, latitude, longitude);
      setDistanceM((d) => d + stepDistance);

      if (altitude != null && last.altitude != null) {
        const altitudeDelta = altitude - last.altitude;
        // only count uphill movement -- "elevation gain" is the sum of
        // climbs, not net elevation change, same definition used for every
        // trail's elevation_gain_m in the backend's feature pipeline
        if (altitudeDelta > 0) {
          setElevationGainM((e) => e + altitudeDelta);
        }
      }
    }

    lastPositionRef.current = { lat: latitude, lon: longitude, altitude };
  }, []);

  const startWatching = useCallback(async () => {
    const { status: permissionStatus } = await Location.requestForegroundPermissionsAsync();
    if (permissionStatus !== 'granted') {
      throw new Error('Location permission is required to track a hike');
    }

    subscriptionRef.current = await Location.watchPositionAsync(
      {
        accuracy: Location.Accuracy.BestForNavigation,
        distanceInterval: 5, // meters -- ignore GPS jitter smaller than this
        timeInterval: 2000,
      },
      onLocationUpdate
    );

    timerRef.current = setInterval(() => {
      setElapsedMs(Date.now() - startedAtRef.current - pausedAccumulatedMsRef.current);
    }, 1000);
  }, [onLocationUpdate]);

  const stopWatching = useCallback(() => {
    subscriptionRef.current?.remove();
    subscriptionRef.current = null;
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const start = useCallback(
    async (name: string, osmId: number) => {
      setTrailName(name);
      setDistanceM(0);
      setElevationGainM(0);
      setElapsedMs(0);
      lastPositionRef.current = null;
      pausedAccumulatedMsRef.current = 0;
      startedAtRef.current = Date.now();
      osmIdRef.current = osmId;

      await startWatching();
      setStatus('active');
    },
    [startWatching]
  );

  const pause = useCallback(() => {
    stopWatching();
    pausedAtRef.current = Date.now();
    setStatus('paused');
  }, [stopWatching]);

  const resume = useCallback(async () => {
    // the time spent paused shouldn't count toward elapsed time, so it gets
    // folded into the running "paused total" that's subtracted every tick
    pausedAccumulatedMsRef.current += Date.now() - pausedAtRef.current;
    // a fresh GPS fix after resuming could be far from where tracking
    // stopped (device moved while paused, or just GPS drift) -- discard the
    // last known point so that gap isn't counted as hiked distance
    lastPositionRef.current = null;
    await startWatching();
    setStatus('active');
  }, [startWatching]);

  const finish = useCallback((): { distanceM: number; elapsedS: number; osmId: number | null } => {
    stopWatching();
    const result = { distanceM, elapsedS: elapsedMs / 1000, osmId: osmIdRef.current };
    setStatus('idle');
    setTrailName(null);
    setDistanceM(0);
    setElevationGainM(0);
    setElapsedMs(0);
    osmIdRef.current = null;
    return result;
  }, [stopWatching, distanceM, elapsedMs]);

  return (
    <ActiveHikeContext.Provider
      value={{ status, trailName, distanceM, elevationGainM, elapsedMs, start, pause, resume, finish }}
    >
      {children}
    </ActiveHikeContext.Provider>
  );
}

export function useActiveHike(): ActiveHikeContextValue {
  const context = useContext(ActiveHikeContext);
  if (!context) {
    throw new Error('useActiveHike must be used within an ActiveHikeProvider');
  }
  return context;
}
