import * as Location from 'expo-location';
import * as TaskManager from 'expo-task-manager';
import { haversineMeters } from './geo';
import { syncPendingHikes } from './pendingHikes';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react';

type Status = 'idle' | 'active' | 'paused';

type ActiveHikeContextValue = {
  status: Status;
  // bumped once per start() call (never on resume()) -- lets screens that
  // stay mounted across multiple hikes (so GPS tracking survives a tab
  // switch) detect "a genuinely new hike just began" and reset their own
  // per-hike-session state (stale finish summary, map camera position)
  // accordingly, without reacting to every pause/resume too
  sessionId: number;
  trailName: string | null;
  osmId: number | null;
  distanceM: number;
  elevationGainM: number;
  elapsedMs: number;
  // every GPS fix recorded so far, as [lon, lat] pairs -- same coordinate
  // order used everywhere else in the app (trail geometry, map polylines)
  pathCoords: [number, number][];
  currentPosition: [number, number] | null;
  start: (trailName: string, osmId: number) => Promise<void>;
  pause: () => void;
  resume: () => Promise<void>;
  finish: () => {
    distanceM: number;
    elapsedS: number;
    elevationGainM: number;
    osmId: number | null;
    trailName: string | null;
  };
};

const ActiveHikeContext = createContext<ActiveHikeContextValue | null>(null);

// a hiking app's whole reason to track location at all is to record a route
// that keeps recording after the screen locks -- nobody keeps their phone
// unlocked and the app open for a whole hike, so background-capable
// tracking is the only mode this app supports; there's no foreground-only
// fallback to fall back to
const LOCATION_TASK_NAME = 'trail-app-background-location';

// TaskManager requires this defined at module scope, not inside a
// component, so it's registered every time the app launches (including a
// relaunch the OS triggers in the background purely to deliver a location
// update). Its closure can't reach into a particular component instance's
// state directly, so it forwards each update to whichever handler
// ActiveHikeProvider has currently registered below.
let activeLocationHandler: ((location: Location.LocationObject) => void) | null = null;

TaskManager.defineTask(LOCATION_TASK_NAME, async ({ data, error }) => {
  if (error || !data) return;
  const { locations } = data as { locations: Location.LocationObject[] };
  for (const location of locations) {
    activeLocationHandler?.(location);
  }
});


export function ActiveHikeProvider({ children }: PropsWithChildren) {
  const [status, setStatus] = useState<Status>('idle');
  const [sessionId, setSessionId] = useState(0);
  const [trailName, setTrailName] = useState<string | null>(null);
  const [osmId, setOsmId] = useState<number | null>(null);
  const [distanceM, setDistanceM] = useState(0);
  const [elevationGainM, setElevationGainM] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [pathCoords, setPathCoords] = useState<[number, number][]>([]);
  const [currentPosition, setCurrentPosition] = useState<[number, number] | null>(null);

  // refs, not state -- these drive accumulation logic between renders but
  // don't themselves need to trigger a re-render when they change
  const lastPositionRef = useRef<{ lat: number; lon: number; altitude: number | null } | null>(
    null
  );
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedAtRef = useRef<number>(0);
  const pausedAccumulatedMsRef = useRef<number>(0);
  const pausedAtRef = useRef<number>(0);

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
    setCurrentPosition([longitude, latitude]);
    setPathCoords((coords) => [...coords, [longitude, latitude]]);
  }, []);

  // ActiveHikeProvider wraps the whole app and is never unmounted during
  // normal use, so this effectively registers once for the app's lifetime
  // -- but it's still done via effect (not a plain module assignment)
  // so it's correctly re-pointed if this ever did remount
  useEffect(() => {
    activeLocationHandler = onLocationUpdate;
    return () => {
      activeLocationHandler = null;
    };
  }, [onLocationUpdate]);

  // catches the case where a hike finished offline, got queued, and the
  // user reopens the app (now with a connection) without happening to
  // visit the History tab first -- History's own focus effect covers the
  // more common path, this is the belt-and-suspenders one-time fallback
  useEffect(() => {
    syncPendingHikes().catch(() => {});
  }, []);

  const startWatching = useCallback(async () => {
    // foreground permission is a required stepping stone to requesting
    // background permission -- iOS/Android won't grant "Always" without it
    // already granted -- not a separate tracking mode of its own
    const { status: fgStatus } = await Location.requestForegroundPermissionsAsync();
    if (fgStatus !== 'granted') {
      throw new Error('Location permission is required to track a hike');
    }

    const { status: bgStatus } = await Location.requestBackgroundPermissionsAsync();
    if (bgStatus !== 'granted') {
      throw new Error(
        '"Always" location access is required to track a hike, so recording continues while your phone is locked. Enable it in Settings and try again.'
      );
    }

    await Location.startLocationUpdatesAsync(LOCATION_TASK_NAME, {
      accuracy: Location.Accuracy.BestForNavigation,
      distanceInterval: 5, // meters -- ignore GPS jitter smaller than this
      timeInterval: 2000,
      activityType: Location.ActivityType.Fitness,
      showsBackgroundLocationIndicator: true,
      pausesUpdatesAutomatically: false,
      foregroundService: {
        notificationTitle: 'HoggHikes',
        notificationBody: 'Tracking your hike in the background',
      },
    });

    timerRef.current = setInterval(() => {
      setElapsedMs(Date.now() - startedAtRef.current - pausedAccumulatedMsRef.current);
    }, 1000);
  }, []);

  const stopWatching = useCallback(async () => {
    const isRegistered = await TaskManager.isTaskRegisteredAsync(LOCATION_TASK_NAME);
    if (isRegistered) await Location.stopLocationUpdatesAsync(LOCATION_TASK_NAME);
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const start = useCallback(
    async (name: string, newOsmId: number) => {
      setSessionId((id) => id + 1);
      setTrailName(name);
      setOsmId(newOsmId);
      setDistanceM(0);
      setElevationGainM(0);
      setElapsedMs(0);
      setPathCoords([]);
      setCurrentPosition(null);
      lastPositionRef.current = null;
      pausedAccumulatedMsRef.current = 0;
      startedAtRef.current = Date.now();

      await startWatching();
      setStatus('active');
    },
    [startWatching]
  );

  const pause = useCallback(() => {
    // fire-and-forget: pause() is used directly as a button handler and
    // needs to stay synchronous. The native task teardown finishing a beat
    // later doesn't matter -- nothing re-reads tracking state until the
    // next start()/resume() call, well after this resolves in practice.
    void stopWatching();
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

  const finish = useCallback(() => {
    void stopWatching(); // see pause() -- same fire-and-forget reasoning
    const result = { distanceM, elapsedS: elapsedMs / 1000, elevationGainM, osmId, trailName };
    setStatus('idle');
    setTrailName(null);
    setOsmId(null);
    setDistanceM(0);
    setElevationGainM(0);
    setElapsedMs(0);
    setPathCoords([]);
    setCurrentPosition(null);
    return result;
  }, [stopWatching, distanceM, elapsedMs, elevationGainM, osmId, trailName]);

  return (
    <ActiveHikeContext.Provider
      value={{
        status,
        sessionId,
        trailName,
        osmId,
        distanceM,
        elevationGainM,
        elapsedMs,
        pathCoords,
        currentPosition,
        start,
        pause,
        resume,
        finish,
      }}
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
