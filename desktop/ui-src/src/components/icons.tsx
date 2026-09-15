// Hand-drawn 24px stroke icons (carried over from the legacy panel). Each icon is
// its own export so unused ones are tree-shaken.
import type { ComponentChildren } from 'preact';

export interface IconProps {
  size?: number;
}

function svg(children: ComponentChildren, size = 16, strokeWidth = 1.6) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false"
      fill="none" stroke="currentColor" stroke-width={strokeWidth} stroke-linecap="round" stroke-linejoin="round"
    >
      {children}
    </svg>
  );
}

export const IconDashboard = ({ size }: IconProps) => svg(<><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>, size);
export const IconLicense = ({ size }: IconProps) => svg(<><circle cx="8.5" cy="9" r="4.5" /><path d="M11.7 12.2 20 20.5M16 16.5l2-2M13.5 14l1.8-1.8" /></>, size);
export const IconBell = ({ size }: IconProps) => svg(<><path d="M18 9a6 6 0 1 0-12 0c0 5-2 6-2 6h16s-2-1-2-6" /><path d="M10.3 19a2 2 0 0 0 3.4 0" /></>, size);
export const IconSliders = ({ size }: IconProps) => svg(<><path d="M4 7h10M18 7h2M4 12h2M10 12h10M4 17h10M18 17h2" /><circle cx="16" cy="7" r="2" /><circle cx="8" cy="12" r="2" /><circle cx="16" cy="17" r="2" /></>, size);
export const IconFlask = ({ size }: IconProps) => svg(<><path d="M10 3v6L4.7 17.6A2 2 0 0 0 6.4 21h11.2a2 2 0 0 0 1.7-3.4L14 9V3" /><path d="M8.5 3h7M7.5 14h9" /></>, size);
export const IconReceipt = ({ size }: IconProps) => svg(<><path d="M5 3h14v18l-2.3-1.5L14.4 21l-2.4-1.5L9.6 21l-2.3-1.5L5 21V3z" /><path d="M9 8h6M9 12h6" /></>, size);
export const IconPower = ({ size }: IconProps) => svg(<><path d="M12 3v8" /><path d="M6.3 6.5a8 8 0 1 0 11.4 0" /></>, size, 2);
export const IconCopy = ({ size }: IconProps) => svg(<><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></>, size);
export const IconCheck = ({ size }: IconProps) => svg(<path d="M4.5 12.5 10 18 19.5 6.5" />, size, 2);
export const IconRefresh = ({ size }: IconProps) => svg(<><path d="M20 11a8 8 0 0 0-15.3-2M4 13a8 8 0 0 0 15.3 2" /><path d="M4 5v4h4M20 19v-4h-4" /></>, size);
export const IconEye = ({ size }: IconProps) => svg(<><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" /><circle cx="12" cy="12" r="2.8" /></>, size);
export const IconSend = ({ size }: IconProps) => svg(<path d="M21 3 10.5 13.5M21 3l-7 18-3.5-7.5L3 10l18-7z" />, size);
export const IconArrow = ({ size }: IconProps) => svg(<path d="M5 12h14M13 6l6 6-6 6" />, size);
export const IconWarn = ({ size }: IconProps) => svg(<><path d="M12 3 2.5 20h19L12 3z" /><path d="M12 10v4.5M12 17.5v.2" /></>, size);
export const IconTrash = ({ size }: IconProps) => svg(<path d="M4 7h16M9 7V5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 5v2M6.5 7l1 13h9l1-13" />, size);
export const IconGlobe = ({ size }: IconProps) => svg(<><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.7 2.6 4 5.8 4 9s-1.3 6.4-4 9c-2.7-2.6-4-5.8-4-9s1.3-6.4 4-9z" /></>, size);
export const IconDownload = ({ size }: IconProps) => svg(<><path d="M12 3v11M7.5 10.5 12 15l4.5-4.5" /><path d="M4 17v2.5A1.5 1.5 0 0 0 5.5 21h13a1.5 1.5 0 0 0 1.5-1.5V17" /></>, size);
export const IconUpload = ({ size }: IconProps) => svg(<><path d="M12 14V3M7.5 7.5 12 3l4.5 4.5" /><path d="M4 17v2.5A1.5 1.5 0 0 0 5.5 21h13a1.5 1.5 0 0 0 1.5-1.5V17" /></>, size);
export const IconHeart = ({ size }: IconProps) => svg(<path d="M3 12h4l2-5 3.5 10L15 9l1.5 3H21" />, size);
export const IconLogs = ({ size }: IconProps) => svg(<><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 8h8M8 12h8M8 16h5" /></>, size);
export const IconSearch = ({ size }: IconProps) => svg(<><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" /></>, size);
export const IconClose = ({ size }: IconProps) => svg(<path d="M5 5l14 14M19 5L5 19" />, size);
export const IconSun = ({ size }: IconProps) => svg(<><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4" /></>, size);
export const IconMoon = ({ size }: IconProps) => svg(<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />, size);
export const IconMonitor = ({ size }: IconProps) => svg(<><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></>, size);
