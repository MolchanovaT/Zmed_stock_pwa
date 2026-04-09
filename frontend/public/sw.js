// Service Worker для PWA
// Стратегия: Network First (пробуем сеть, при ошибке — кэш)

const CACHE_NAME = 'zmed-stock-v1';

const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
];

// ── Установка: кэшируем статику ────────────────────────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// ── Активация: удаляем старые кэши ────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// ── Fetch: Network First ───────────────────────────────────────────────────────
self.addEventListener('fetch', (event) => {
  // API-запросы не кэшируем
  if (event.request.url.includes('/api/')) {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Успешный ответ — кладём в кэш и возвращаем
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => {
        // Нет сети — берём из кэша
        return caches.match(event.request).then(
          (cached) => cached || caches.match('/index.html')
        );
      })
  );
});
