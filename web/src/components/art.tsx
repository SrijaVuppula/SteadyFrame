// Decorative drawings for the demo page: the logo, a film reel (it turns slowly while a check
// runs; never under reduced motion) and a still thumbnail for each test clip. All are static
// shapes: nothing changes brightness, so nothing here can flash.
import type { ReactNode } from 'react';

export function Logo() {
  return (
    <svg className="sf-logo" viewBox="0 0 28 28" aria-hidden="true">
      <path d="M3 9V5.5A2.5 2.5 0 0 1 5.5 3H9M19 3h3.5A2.5 2.5 0 0 1 25 5.5V9M25 19v3.5a2.5 2.5 0 0 1-2.5 2.5H19M9 25H5.5A2.5 2.5 0 0 1 3 22.5V19"
        fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
      <rect className="sf-logo-core" x="8.5" y="10.5" width="11" height="7" rx="1.8" />
    </svg>
  );
}

export function Reel({ spinning }: { spinning?: boolean }) {
  const holes = [0, 72, 144, 216, 288].map((a) => {
    const r = (a * Math.PI) / 180;
    return <circle key={a} cx={12 + 5.4 * Math.sin(r)} cy={12 - 5.4 * Math.cos(r)} r="2.1" />;
  });
  return (
    <svg className={`sf-reel${spinning ? ' spin' : ''}`} viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="10.5" className="sf-reel-disc" />
      <g className="sf-reel-holes">{holes}<circle cx="12" cy="12" r="1.3" /></g>
    </svg>
  );
}

const THUMBS: Record<string, ReactNode> = {
  sample_strobe_region: (
    <>
      <rect width="64" height="40" fill="#2b2822" />
      <rect x="22" y="12" width="20" height="16" rx="2" fill="#efe7d6" />
      <path d="M32 5v3M32 32v3M15 20h3M46 20h3M19 9l2 2M45 9l-2 2M19 31l2-2M45 31l-2-2" stroke="#f2b84b" strokeWidth="1.6" strokeLinecap="round" />
    </>
  ),
  sample_red_strobe: (
    <>
      <rect width="64" height="40" fill="#2b2822" />
      <rect x="34" y="0" width="30" height="40" fill="#d1372c" />
    </>
  ),
  sample_red_fullscreen: (
    <>
      <rect width="64" height="40" fill="#d1372c" />
      <rect x="3" y="3" width="58" height="34" rx="2" fill="none" stroke="#8f1f18" strokeWidth="1.5" />
    </>
  ),
  sample_clean: (
    <>
      <rect width="64" height="40" fill="#cfe1e4" />
      <circle cx="47" cy="13" r="5" fill="#f2c46d" />
      <path d="M0 31c10-9 20-9 30-3s20 4 34-4v16H0z" fill="#8fb894" />
      <path d="M0 36c14-6 28-6 40-2s16 2 24 0v6H0z" fill="#6f9c78" />
    </>
  ),
};

export function ClipThumb({ id }: { id: string }) {
  return (
    <svg className="sf-thumb" viewBox="0 0 64 40" aria-hidden="true" preserveAspectRatio="xMidYMid slice">
      {THUMBS[id] ?? <rect width="64" height="40" fill="#2b2822" />}
    </svg>
  );
}
