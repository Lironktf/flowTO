/** Inline stroke icons (1.7–1.8 stroke), per the design's icon language. */
import type { ReactNode } from "react";

const S = (children: ReactNode) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
    {children}
  </svg>
);

export const Icon = {
  play: () => S(<polygon points="6 4 20 12 6 20 6 4" fill="currentColor" stroke="none" />),
  pause: () => S(<><rect x="6" y="5" width="4" height="14" rx="1" fill="currentColor" stroke="none" /><rect x="14" y="5" width="4" height="14" rx="1" fill="currentColor" stroke="none" /></>),
  pencil: () => S(<><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></>),
  select: () => S(<path d="M4 4l7 16 2-7 7-2Z" />),
  closure: () => S(<><circle cx="12" cy="12" r="9" /><path d="M5 5l14 14" /></>),
  lane: () => S(<><path d="M12 3v18" strokeDasharray="3 3" /><path d="M6 3v18M18 3v18" /></>),
  oneway: () => S(<><path d="M5 12h14" /><path d="M13 6l6 6-6 6" /></>),
  signal: () => S(<><rect x="9" y="2" width="6" height="20" rx="3" /><circle cx="12" cy="7" r="1.4" fill="currentColor" /><circle cx="12" cy="12" r="1.4" fill="currentColor" /><circle cx="12" cy="17" r="1.4" fill="currentColor" /></>),
  surge: () => S(<path d="M13 2L4 14h7l-1 8 9-12h-7Z" />),
  transit: () => S(<><rect x="5" y="3" width="14" height="14" rx="3" /><path d="M5 11h14M8 21l2-3M16 21l-2-3" /><circle cx="8.5" cy="14" r="1" fill="currentColor" /><circle cx="15.5" cy="14" r="1" fill="currentColor" /></>),
  jumpStart: () => S(<><path d="M19 4v16L9 12zM5 4v16" /></>),
  stepBack: () => S(<><path d="M15 5v14L6 12z" /><path d="M18 5v14" /></>),
  stepFwd: () => S(<><path d="M9 5v14l9-7z" /><path d="M6 5v14" /></>),
  jumpEnd: () => S(<><path d="M5 4v16l10-8zM19 4v16" /></>),
  recenter: () => S(<><circle cx="12" cy="12" r="7" /><path d="M12 1v3M12 20v3M1 12h3M20 12h3" /></>),
  tilt: () => S(<path d="M3 17l9-12 9 12z" />),
  moon: () => S(<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />),
  eye: () => S(<><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></>),
  send: () => S(<path d="M4 12l16-8-6 16-3-7-7-1Z" />),
  check: () => S(<path d="M4 12l5 5L20 6" />),
  warn: () => S(<><path d="M12 3l10 17H2Z" /><path d="M12 10v5M12 18h.01" /></>),
  info: () => S(<><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></>),
  plus: () => S(<><path d="M12 5v14M5 12h14" /></>),
  trash: () => S(<><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13" /></>),
  save: () => S(<><path d="M5 4h11l3 3v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z" /><path d="M8 4v5h7" /><path d="M8 14h8v6H8z" /></>),
  clock: () => S(<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>),
  calendar: () => S(<><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 9h18M8 3v4M16 3v4" /></>),
  pin: () => S(<><path d="M12 21s7-6.2 7-11a7 7 0 0 0-14 0c0 4.8 7 11 7 11Z" /><circle cx="12" cy="10" r="2.5" /></>),
  chart: () => S(<><path d="M4 19V5M4 19h16" /><path d="M7 16l4-5 3 3 4-6" /></>),
};

export type IconKey = keyof typeof Icon;
