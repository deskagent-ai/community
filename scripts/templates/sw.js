/**
 * DeskAgent Service Worker
 * Shows a loading page when server is not reachable (instead of browser error)
 */

const CACHE_NAME = 'deskagent-offline-v1';
const OFFLINE_URL = '/offline.html';

// Install: Cache the offline page
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.add(OFFLINE_URL))
    );
    self.skipWaiting();
});

// Activate: Clean old caches
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

// Fetch: Show offline page on network errors for navigation requests
self.addEventListener('fetch', event => {
    // Only handle navigation requests (page loads)
    if (event.request.mode !== 'navigate') return;

    event.respondWith(
        fetch(event.request).catch(() =>
            caches.match(OFFLINE_URL)
        )
    );
});
