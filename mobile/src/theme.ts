// Single source of truth for color across the app -- black/near-black
// surfaces with a maroon accent, no gradients. Map polyline colors are
// intentionally NOT drawn from here: a route line and a recorded track
// need to read as two distinct things at a glance, so those stay their
// own functional greens/blues rather than being forced into the brand
// palette (see active-hike.tsx, index.tsx).
export const colors = {
  background: '#0d0d0d',
  surface: '#1a1414',
  surfaceRaised: '#231b1c',
  border: '#332828',

  maroon: '#9c2b3d',
  maroonDark: '#7a2130',
  maroonLight: '#c2425a',

  text: '#f2efef',
  textSecondary: '#a89a9a',
  textMuted: '#6e6262',

  // deliberately a brighter, more saturated red than the maroon brand
  // color -- an error needs to read as distinct from a primary button,
  // not as a duller version of the same hue
  error: '#e5484d',
  // muted amber rather than a bright traffic-light orange, to stay in
  // register with the rest of the dark/maroon palette
  warning: '#b8860b',

  white: '#ffffff',
};
