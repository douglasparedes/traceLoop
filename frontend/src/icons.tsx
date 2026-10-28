// Offline-safe inline icon set (24px, stroke-based, currentColor).
// Keeps the Stitch icon language without an external font/CDN dependency.
import type { JSX } from "react";

type P = { size?: number; className?: string };

function Svg({ size = 20, className, children }: P & { children: React.ReactNode }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

const ic = (el: JSX.Element) => (_: P) => <Svg {..._}>{el}</Svg>;

export const Icons = {
  home: ic(<><path d="M3 11.5 12 3l9 8.5" /><path d="M5.5 10.5V21h5v-6h3v6h5v-10.5" /></>),
  book: ic(<><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z" /><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5" /></>),
  addBox: ic(<><rect x="3.5" y="3.5" width="17" height="17" rx="3" /><path d="M12 8.5v7M8.5 12h7" /></>),
  schedule: ic(<><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>),
  mic: ic(<><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3" /></>),
  camera: ic(<><path d="M4 8h3l2-2.5h6L17 8h3a1.5 1.5 0 0 1 1.5 1.5V19a1.5 1.5 0 0 1-1.5 1.5H4A1.5 1.5 0 0 1 2.5 19V9.5A1.5 1.5 0 0 1 4 8z" /><circle cx="12" cy="13.5" r="3.5" /></>),
  videocam: ic(<><rect x="2.5" y="6.5" width="13" height="11" rx="2.5" /><path d="m15.5 10.5 6-3.5v10l-6-3.5" /></>),
  back: ic(<><path d="M19 12H5M11 6l-6 6 6 6" /></>),
  forward: ic(<><path d="M5 12h14M13 6l6 6-6 6" /></>),
  chevronRight: ic(<><path d="m9 5 7 7-7 7" /></>),
  check: ic(<><path d="m4.5 12.5 5 5 10-11" /></>),
  checkCircle: ic(<><circle cx="12" cy="12" r="8.5" /><path d="m8.5 12.2 2.5 2.5 4.8-5.5" /></>),
  warning: ic(<><path d="M12 3.5 22 20H2z" /><path d="M12 10v4.5M12 17.8v.2" /></>),
  error: ic(<><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V13M12 16.2v.2" /></>),
  search: ic(<><circle cx="11" cy="11" r="6.5" /><path d="m16 16 5 5" /></>),
  sort: ic(<><path d="M7 4v13M4 14l3 3 3-3M17 20V7M14 10l3-3 3 3" /></>),
  download: ic(<><path d="M12 3.5V15M7.5 10.5 12 15l4.5-4.5M4 19.5h16" /></>),
  upload: ic(<><path d="M12 15V3.5M7.5 8 12 3.5 16.5 8M4 19.5h16" /></>),
  cloudDone: ic(<><path d="M7 18.5a4.5 4.5 0 0 1-.4-9A6 6 0 0 1 18 8.5a4.2 4.2 0 0 1-.5 10z" /><path d="m10 13.5 2.2 2.2 3.3-4" /></>),
  verified: ic(<><path d="M12 2.8 20 6v6c0 5-3.5 8-8 9.2C7.5 20 4 17 4 12V6z" /><path d="m8.8 12 2.2 2.2 4.2-4.7" /></>),
  play: ({ size = 20 }: P) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false"><path d="M8 5.5v13l11-6.5z" /></svg>
  ),
  stop: ({ size = 20 }: P) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false"><rect x="6.5" y="6.5" width="11" height="11" rx="2" /></svg>
  ),
  eye: ic(<><path d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12z" /><circle cx="12" cy="12" r="2.8" /></>),
  edit: ic(<><path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17z" /><path d="m13.5 6.5 3 3" /></>),
  note: ic(<><path d="M5 3.5h11L20.5 8v12.5h-15.5z" /><path d="M9 12h7M9 15.5h7M9 8.5h3" /></>),
  trash: ic(<><path d="M4 6.5h16M9.5 6.5v-2h5v2M6.5 6.5 7.5 21h9l1-14.5" /><path d="M10 10.5v7M14 10.5v7" /></>),
  close: ic(<><path d="M6 6l12 12M18 6 6 18" /></>),
  scan: ic(<><path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4" /><path d="M4 12h16" /></>),
  factory: ic(<><path d="M3 21V10l5 3v-3l5 3V7h8v14z" /><path d="M3 21h18" /></>),
  domain: ic(<><rect x="4.5" y="3.5" width="15" height="17" rx="1.5" /><path d="M9 8h2M13 8h2M9 12h2M13 12h2M10 20.5v-3h4v3" /></>),
  clip: ic(<><path d="m8 12.5 6.5-6.5a2.4 2.4 0 0 1 3.4 3.4l-8 8a4.6 4.6 0 0 1-6.5-6.5l7-7" /></>),
  sync: ic(<><path d="M20 12a8 8 0 0 1-14.5 4.6M4 12a8 8 0 0 1 14.5-4.6" /><path d="M18.5 3.5v4h-4M5.5 20.5v-4h4" /></>),
  bolt: ic(<><path d="M13 2.5 4.5 13.5H11l-1 8 8.5-11H12z" /></>),
  lock: ic(<><rect x="5" y="10.5" width="14" height="10" rx="2" /><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" /></>),
  drop: ic(<><path d="M12 3s6 6.3 6 11a6 6 0 0 1-12 0c0-4.7 6-11 6-11z" /></>),
  library: ic(<><rect x="3" y="4" width="8" height="16" rx="1.5" /><rect x="12.5" y="4" width="8" height="16" rx="1.5" /></>),
  flag: ic(<><path d="M5 21V4" /><path d="M5 4.5h12.5l-2.5 4 2.5 4H5" /></>),
  grid: ic(<><rect x="4" y="4" width="7" height="7" rx="1.5" /><rect x="13" y="4" width="7" height="7" rx="1.5" /><rect x="4" y="13" width="7" height="7" rx="1.5" /><rect x="13" y="13" width="7" height="7" rx="1.5" /></>),
  cog: ic(<><circle cx="12" cy="12" r="3" /><path d="M12 2.8v3M12 18.2v3M2.8 12h3M18.2 12h3M5.5 5.5l2.1 2.1M16.4 16.4l2.1 2.1M18.5 5.5l-2.1 2.1M7.6 16.4l-2.1 2.1" /></>),
  timer: ic(<><circle cx="12" cy="13.5" r="7.5" /><path d="M12 10v3.5l2.5 1.5M9.5 2.5h5" /></>),
  bot: ic(<><rect x="5" y="9" width="14" height="10" rx="2.5" /><circle cx="9.5" cy="13.5" r=".8" /><circle cx="14.5" cy="13.5" r=".8" /><path d="M12 9V4.5M9 16.5h6" /></>),
  shield: ic(<><path d="M12 2.8 20 6v6c0 5-3.5 8-8 9.2C7.5 20 4 17 4 12V6z" /></>),
  pin: ic(<><path d="M12 21.5s6.5-6 6.5-11a6.5 6.5 0 1 0-13 0c0 5 6.5 11 6.5 11z" /><circle cx="12" cy="10.5" r="2.3" /></>),
  folder: ic(<><path d="M3.5 6.5h6l2 2.5h9v10h-17z" /></>),
};

export type IconName = keyof typeof Icons;

export function Icon({ name, size = 20, className }: { name: IconName; size?: number; className?: string }) {
  const C = Icons[name];
  return (
    <span className={`icon${className ? ` ${className}` : ""}`} aria-hidden="true">
      <C size={size} />
    </span>
  );
}
