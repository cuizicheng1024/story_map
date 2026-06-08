function getApiBase() {
  const globalBase = window.MAP_STORY_API_BASE || window.MAP_STORY_BACKEND_BASE;
  if (typeof globalBase === "string" && globalBase.trim()) {
    return globalBase.replace(/\/+$/, "");
  }
  if (import.meta.env.VITE_API_BASE) {
    return import.meta.env.VITE_API_BASE.replace(/\/+$/, "");
  }
  const { origin, hostname, protocol } = window.location;
  if (protocol !== "file:" && origin && origin !== "null" && hostname !== "localhost" && hostname !== "127.0.0.1") {
    return origin.replace(/\/+$/, "");
  }
  return "";
}

const API_BASE = getApiBase();

function buildUrl(path) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return API_BASE ? `${API_BASE}${normalizedPath}` : normalizedPath;
}

async function requestJson(path, options = {}) {
  const response = await fetch(buildUrl(path), {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    },
    ...options
  });

  const data = await response.json().catch(() => null);
  if (!response.ok || data?.ok === false) {
    throw new Error(data?.error || `请求失败: ${response.status}`);
  }
  return data;
}

export async function submitGenerateTask(text) {
  return requestJson("/generate", {
    method: "POST",
    body: JSON.stringify({ text })
  });
}

export async function fetchTaskStatus(taskId) {
  return requestJson(`/task?id=${encodeURIComponent(taskId)}`, {
    method: "GET"
  });
}
