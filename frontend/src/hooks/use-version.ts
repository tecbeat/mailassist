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
  /**
   * GitLab URL for this version.
   * - CI builds  → specific release page (…/releases/v1.2.3)
   * - Dev builds → releases list        (…/releases)
   * null only while the health endpoint hasn't responded yet.
   */
  releaseUrl: string | null;
}

/** Returns true for CI-produced versions (not the 0.0.0-dev local default). */
function isReleaseVersion(v: string): boolean {
  return !v.startsWith("0.0.0");
}

/**
 * Fetches the running app version from /health and derives the GitLab release URL.
 * Always provides a link — specific release for CI builds, releases list for dev.
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

  const releaseUrl = normalised
    ? isReleaseVersion(normalised)
      ? `${RELEASE_BASE}/v${normalised}`
      : RELEASE_BASE
    : null;

  return { version: normalised ?? null, releaseUrl };
}
