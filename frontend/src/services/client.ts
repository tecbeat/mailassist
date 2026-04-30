/**
 * Custom fetch instance for orval generated API client.
 * Orval calls this as customInstance(url, requestInit).
 * Handles credentials, CSRF tokens, 401 redirects, and JSON error parsing.
 */

/** Read a cookie value by name from document.cookie. */
function getCookie(name: string): string | undefined {
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`));
  return match?.split("=")[1];
}

/** HTTP methods that require a CSRF token (double-submit cookie pattern). */
const CSRF_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export async function customInstance<T>(
  url: string,
  options?: RequestInit
): Promise<T> {
  const headers: Record<string, string> = {};

  // Copy existing headers
  if (options?.headers) {
    const h = options.headers;
    if (h instanceof Headers) {
      h.forEach((v, k) => {
        headers[k] = v;
      });
    } else if (Array.isArray(h)) {
      h.forEach(([k, v]) => {
        headers[k] = v;
      });
    } else {
      Object.assign(headers, h);
    }
  }

  // Set Content-Type for JSON bodies (orval passes stringified JSON)
  if (options?.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  // Attach CSRF token for state-changing requests (double-submit cookie pattern).
  // The backend CSRFMiddleware sets an httponly=false csrf_token cookie and
  // expects it echoed back via the X-CSRF-Token header.
  const method = (options?.method ?? "GET").toUpperCase();
  if (CSRF_METHODS.has(method)) {
    const csrfToken = getCookie("csrf_token");
    if (csrfToken) {
      headers["X-CSRF-Token"] = csrfToken;
    }
  }

  const response = await fetch(url, {
    ...options,
    headers,
    credentials: "include",
  });

  if (response.status === 401) {
    // Avoid redirect loops: if already on an auth page, just throw.
    if (!window.location.pathname.startsWith("/auth/")) {
      window.location.href = "/auth/login";
    }
    throw new Error("Unauthorized");
  }

  if (!response.ok) {
    const errorBody = await response.text();
    let message: string;
    try {
      const parsed = JSON.parse(errorBody);
      message = parsed.detail || parsed.message || errorBody;
    } catch {
      message = errorBody;
    }
    throw new Error(message);
  }

  if (response.status === 204) {
    return { data: undefined, status: response.status, headers: response.headers } as T;
  }

  const data = await response.json();
  return { data, status: response.status, headers: response.headers } as T;
}

export default customInstance;
