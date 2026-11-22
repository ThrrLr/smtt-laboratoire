importScripts('https://www.gstatic.com/firebasejs/10.13.2/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.13.2/firebase-messaging-compat.js');

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
  const notif = payload.notification || {};

  const titre = donnees.title || notif.title || "Stade Montois TT";
  const corps = donnees.body || notif.body || "Une nouvelle information est disponible.";
  const url = donnees.appUrl || donnees.url || "https://thrrlr.github.io/smtt/";
  const tag = donnees.notificationId || `smtt-${Date.now()}`;

  return self.registration.showNotification(titre, {
    body: corps,
    icon: "./icons/icon-192.png",
    tag: tag,
    renotify: false,
    data: { url: url }
  });
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  const url =
    event.notification.data?.url ||
    "https://thrrlr.github.io/smtt/";

  event.waitUntil(
    clients.matchAll({
      type: "window",
      includeUncontrolled: true
    }).then((clientList) => {
      for (const client of clientList) {
        if (
          client.url.startsWith("https://thrrlr.github.io/smtt/") &&
          "focus" in client
        ) {
          client.navigate(url);
          return client.focus();
        }
      }

      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});
