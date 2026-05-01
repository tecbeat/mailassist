import { useEffect, useState } from "react";
import { customInstance } from "@/services/client";

const RELEASE_BASE = "https://git.teccave.de/tecbeat/mailassist/-/releases";

interface HealthResponse {
  status: string;
  version: string;
  services: Record<string, string>;
}

interface UseVersionResult {
  version: string | null;
  /** Full GitLab release URL, or null when version is unknown or "dev". */
  releaseUrl: string | null;
}

/**
 * Fetches the running app version from /health and derives the GitLab release URL.
 * Returns null values while loading or if the endpoint is unreachable.
 */
export function useVersion(): UseVersionResult {
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    customInstance<{ data: HealthResponse }>("/health")
      .then((res) => {
        if (!cancelled) setVersion(res.data.version);
      })
      .catch(() => {
        // Health endpoint unreachable — ignore silently
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const normalised = version?.startsWith("v") ? version.slice(1) : version;
  const releaseUrl =
    normalised && normalised !== "dev"
      ? `${RELEASE_BASE}/v${normalised}`
      : null;

  return { version: normalised ?? null, releaseUrl };
}
