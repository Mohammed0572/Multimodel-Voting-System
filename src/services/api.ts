const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function parseResponse(response: Response) {
  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "The server rejected the request.",
    );
  }

  return data;
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const cleanBase = API_BASE_URL.replace(/\/+$/, "");
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  const url =
    cleanBase.endsWith("/api/v1") && cleanPath.startsWith("/api/v1")
      ? `${cleanBase}${cleanPath.slice(7)}`
      : `${cleanBase}${cleanPath}`;

  const response = await fetch(url, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  });

  return parseResponse(response) as Promise<T>;
}

export function castVote(candidateId: number) {
  return apiRequest<{
    success: boolean;
    transaction_hash: string;
    tx_hash?: string;
  }>("/api/v1/voter/cast", {
    method: "POST",
    body: JSON.stringify({
      candidate_id: candidateId,
    }),
  });
}
