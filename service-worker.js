
importScripts('https://www.gstatic.com/firebasejs/10.13.2/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.13.2/firebase-messaging-compat.js');

const CACHE = "smtt-v43";

const FILES = [
  "./",
  "./index.html",
  "./style.css",
  "./app.js",
  "./manifest.webmanifest",
  "./icons/icon.svg",
  "./icons/logo-smtt.svg"
];

firebase.initializeApp({
  apiKey: "AIzaSyCi0apSMq-xuZAj-rahE32w5HXtOh604oU",
  authDomain: "smtt-notifications.firebaseapp.com",
  projectId: "smtt-notifications",
  storageBucket: "smtt-notifications.firebasestorage.app",
  messagingSenderId: "671610991236",
  appId: "1:671610991236:web:63efe6ead81520de6988d1"
});

const messaging = firebase.messaging();

messaging.onBackgroundMessage((payload) => {
  const donnees = payload.data || {};
  const notification = payload.notification || {};

  const titre =
    notification.title ||
    donnees.title ||
    "Stade Montois TT";

  const corps =
    notification.body ||
    donnees.body ||
    "Une nouvelle information est disponible.";

  const url =
    donnees.appUrl ||
    "https://thrrlr.github.io/smtt/";

  return self.registration.showNotification(titre, {
    body: corps,
    icon: notification.icon || "./icons/icon.svg",
    data: { url: url }
  });
});

self.addEventListener("notificationclick", event => {
  event.notification.close();

  const url =
    event.notification.data?.url ||
    "https://thrrlr.github.io/smtt/";

  event.waitUntil(
    self.clients.matchAll({
      type: "window",
      includeUncontrolled: true
    }).then(clientList => {
      for (const client of clientList) {
        if (
          client.url.startsWith("https://thrrlr.github.io/smtt/") &&
          "focus" in client
        ) {
          return client.focus();
        }
      }

      return self.clients.openWindow(url);
    })
  );
});

self.addEventListener("install", event => {
  self.skipWaiting();

  event.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(FILES))
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(key => key !== CACHE)
          .map(key => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  event.respondWith(
    caches.match(event.request).then(cached =>
      cached || fetch(event.request)
    )
  );
});
