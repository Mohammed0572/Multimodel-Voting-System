const defaultApiHost =
  typeof window !== "undefined" ? window.location.hostname : "127.0.0.1";
const configuredApiBase =
  import.meta.env.VITE_API_BASE_URL || `http://${defaultApiHost}:8000`;

const apiUrl = new URL(configuredApiBase);
const localHosts = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);

// Keep local frontend/API requests on the same site so SameSite=Lax auth
// cookies are sent by the browser (localhost and 127.0.0.1 are distinct sites).
if (
  typeof window !== "undefined" &&
  localHosts.has(apiUrl.hostname) &&
  localHosts.has(window.location.hostname)
) {
  apiUrl.hostname = window.location.hostname;
}

const apiPath = apiUrl.pathname.replace(/\/+$/, "");
if (!apiPath.endsWith("/api/v1")) {
  apiUrl.pathname = `${apiPath}/api/v1`;
}

export const API_BASE = apiUrl.toString().replace(/\/+$/, "");
