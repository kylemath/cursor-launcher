const CACHE = "cursor-launcher-v1";
const PRECACHE = [
  "manifest.webmanifest",
  "icon-192.png",
  "icon-512.png",
  "apple-touch-icon.png",
  "favicon-32.png",
  "favicon-16.png",
];

const NETWORK_ONLY_PREFIXES = [
  "/open-",
  "/launch",
  "/stop",
  "/save",
  "/git",
  "/publish",
  "/clone",
  "/new-",
  "/capture",
  "/autogen",
  "/refresh",
  "/regenerate",
  "/suggest",
  "/project",
  "/screenshot",
  "/ports",
  "/status",
  "/app-status",
  "/toggle",
  "/shutdown",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

function isNetworkOnly(pathname) {
  if (pathname === "/" || pathname.endsWith("/") || pathname.endsWith("/dashboard.html")) {
    return true;
  }
  return NETWORK_ONLY_PREFIXES.some((prefix) => pathname.includes(prefix));
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET") return;
  if (url.origin !== self.location.origin) return;
  if (isNetworkOnly(url.pathname)) return;

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        const type = response.headers.get("content-type") || "";
        if (response.ok && !type.includes("text/html")) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        }
        return response;
      });
    })
  );
});
