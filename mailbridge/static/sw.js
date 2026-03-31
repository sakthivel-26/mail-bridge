const CACHE_NAME = "mailbridge-v1";
const ASSETS_TO_CACHE = [
  "/",
  "/static/index.html",
  "/static/manifest.json",
];

// Install event - cache essential assets
self.addEventListener("install", event => {
  console.log("✓ Service Worker Installing...");
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log("✓ Caching assets");
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
  self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener("activate", event => {
  console.log("✓ Service Worker Activating...");
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(name => {
          if (name !== CACHE_NAME) {
            console.log("✓ Deleting old cache:", name);
            return caches.delete(name);
          }
        })
      );
    })
  );
  self.clients.claim();
});

// Fetch event - serve from cache, fallback to network
self.addEventListener("fetch", event => {
  // Skip non-GET requests
  if (event.request.method !== "GET") {
    return;
  }

  event.respondWith(
    caches.match(event.request).then(response => {
      // Return cached response if available
      if (response) {
        return response;
      }

      // Otherwise fetch from network
      return fetch(event.request)
        .then(response => {
          // Don't cache if not ok or for external requests
          if (!response || response.status !== 200) {
            return response;
          }

          // Clone the response
          const responseToCache = response.clone();

          // Cache successful API and asset responses
          if (event.request.url.includes("/static/") || 
              event.request.url.includes("/health")) {
            caches.open(CACHE_NAME).then(cache => {
              cache.put(event.request, responseToCache);
            });
          }

          return response;
        })
        .catch(() => {
          // Return offline fallback if available
          if (event.request.destination === "document") {
            return caches.match("/static/index.html");
          }
          return new Response("Offline - please check your connection", {
            status: 503,
            statusText: "Service Unavailable",
            headers: new Headers({
              "Content-Type": "text/plain"
            })
          });
        });
    })
  );
});