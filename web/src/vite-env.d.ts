/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API base URL. Default "/api" (same origin; CloudFront / vite proxy route it). */
  readonly VITE_API_BASE?: string;
  /** "1" serves bundled fixtures instead of the network (also enabled by ?fixture=1). */
  readonly VITE_MOCK_API?: string;
}
