
importScripts('https://www.gstatic.com/firebasejs/10.13.2/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.13.2/firebase-messaging-compat.js');

const CACHE = "smtt-v40";
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
  apiKey: "AIzaSyCi0apSMq-xuZAj-rahE32w5HXtOh604o",
  authDomain: "smtt-notifications.firebaseapp.com",
  projectId: "smtt-notifications",
  storageBucket: "smtt-notifications.firebasestorage.app",
  messagingSenderId: "671610991236",
  appId: "1:671610991236:web:63efe6ead81520de6988d1"
});

const messaging = firebase.messaging();

messaging.onBackgroundMessage((payload) => {
  const titre = payload.notification?.title || "Stade Montois TT";

  const options = {
    body: payload.notification?.body || "Une nouvelle information est disponible.",
    icon: "./icons/icon.svg"
  };

  self.registration.showNotification(titre, options);
});

self.addEventListener("notificationclick", event => {
  event.notification.close();

  event.waitUntil(
    self.clients.matchAll({
      type: "window",
      includeUncontrolled: true
    }).then(clientList => {
      for (const client of clientList) {
        if ("focus" in client) return client.focus();
      }
      return self.clients.openWindow("./");
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
    caches.keys().then(keys => Promise.all(
      keys.filter(key => key !== CACHE).map(key => caches.delete(key))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  event.respondWith(
    caches.match(event.request).then(cached =>
      cached || fetch(event.request)
    )
  );
});
