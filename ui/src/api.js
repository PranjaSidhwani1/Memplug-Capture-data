const TOKEN_KEY = "memplug.capture.token";

export function storedToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function storeToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function parseError(response) {
  const data = await response.json().catch(() => ({}));
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail.map((item) => item.msg || "Invalid input").join(" ");
  }
  return "Request failed";
}

async function request(path, { method = "GET", body, token } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = new Error(await parseError(response));
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) return null;
  const type = response.headers.get("content-type") || "";
  if (!type.includes("application/json")) return null;
  return response.json();
}

export function signup(email, password, name) {
  return request("/v1/auth/signup", { method: "POST", body: { email, password, name } });
}

export function login(email, password) {
  return request("/v1/auth/login", { method: "POST", body: { email, password } });
}

export function me(token) {
  return request("/v1/auth/me", { token });
}

export function listKeys(token) {
  return request("/v1/keys", { token });
}

export function createKey(token, name) {
  return request("/v1/keys", { method: "POST", token, body: { name } });
}

export function revokeKey(token, id) {
  return request(`/v1/keys/${id}`, { method: "DELETE", token });
}

export function configMeta(token) {
  return request("/v1/config/meta", { token });
}

export async function downloadBundle(token, tool, osName, keyId) {
  const params = new URLSearchParams({ tool, os: osName, key_id: keyId });
  const response = await fetch(`/v1/config/bundle?${params}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = new Error(await parseError(response));
    error.status = response.status;
    throw error;
  }
  const blob = await response.blob();
  const header = response.headers.get("Content-Disposition") || "";
  const match = header.match(/filename="([^"]+)"/);
  const filename = match ? match[1] : `memplug-${tool}-${osName}.json`;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  return filename;
}
