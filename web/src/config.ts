// Runtime configuration. Everything here is decided once at startup.

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '') || '/api';

/** Fixture mode: bundled JSON instead of the network. Used by `npm run a11y` and offline demos. */
export const MOCK_MODE: boolean =
  import.meta.env.VITE_MOCK_API === '1' ||
  new URLSearchParams(window.location.search).get('fixture') === '1';

/** Mirrors the server-side limits in docs/API.md; the server is the authority. */
export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
export const MAX_DURATION_S = 120;
export const ACCEPTED_EXTENSIONS = ['mp4', 'mov', 'webm', 'mkv', 'gif'];

export const POLL_MS = 2000;

/** The one sentence we use to describe what the tool does. Do not paraphrase. */
export const WHAT_IT_DOES =
  'checks video against published photosensitivity thresholds (WCAG 2.3.1, ITU-R BT.1702 / Ofcom guidance)';
