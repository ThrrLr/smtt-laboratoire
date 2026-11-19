
// ==========================================
// STADE MONTOIS TT - APPLICATION LABORATOIRE
// ==========================================

const firebaseConfig = {
  apiKey: "AIzaSyCi0apSMq-xuZAj-rahE32w5HXtOh604oU",
  authDomain: "smtt-notifications.firebaseapp.com",
  projectId: "smtt-notifications",
  storageBucket: "smtt-notifications.firebasestorage.app",
  messagingSenderId: "671610991236",
  appId: "1:671610991236:web:63efe6ead81520de6988d1"
};

const VAPID_KEY = "BE9m8DH54RCwCNsmuoqHTYZd1a3DelQju4Hgf6pcc1dkISl5bucpVC76jRoPldtBCNgL35yw14nklfU5owb-M6U";

if (!firebase.apps.length) {
  firebase.initializeApp(firebaseConfig);
}

const auth = firebase.auth();
const db = firebase.firestore();

// ==========================================
// CONTENU DES RUBRIQUES
// ==========================================

const content = {
  equipes: [
    "Équipes",
    "Les compositions, calendriers et résultats des équipes seront ajoutés ici."
  ],
  videos: [
    "Vidéos",
    "Les vidéos et les directs YouTube du club seront accessibles ici."
  ],
  facebook: [
    "Facebook",
    "Le lien vers la page Facebook du club sera ajouté ici."
  ],
  whatsapp: [
    "WhatsApp",
    "Les liens d'invitation vers les groupes WhatsApp seront ajoutés ici."
  ],
  calendrier: [
    "Calendrier",
    "Le calendrier des entraînements et compétitions sera intégré ici."
  ],
  helloasso: [
    "HelloAsso",
    "Le lien HelloAsso du club sera ajouté ici."
  ],
  documents: [
    "Documents",
    "Les documents utiles aux licenciés seront rangés ici."
  ],
  liens: [
    "Liens externes",
    `Accédez directement aux sites officiels des instances :
    <div style="display:grid;gap:10px;margin-top:12px;">
      <a class="tile" href="https://lnatt.fr" target="_blank" rel="noopener noreferrer" style="min-height:auto;padding:14px;">
        <strong>🌐 Ligue Nouvelle-Aquitaine (LNATT)</strong>
        <small>Compétitions régionales, règlements et actualités</small>
      </a>
      <a class="tile" href="https://cd40tt.com" target="_blank" rel="noopener noreferrer" style="min-height:auto;padding:14px;">
        <strong>🏓 Comité des Landes (CD40TT)</strong>
        <small>Critérium départemental et championnats des Landes</small>
      </a>
    </div>`
  ]
};

// ==========================================
// AFFICHAGE DES RUBRIQUES
// ==========================================

document.querySelectorAll("[data-section]").forEach(link => {
  link.addEventListener("click", event => {
    event.preventDefault();

    const [title, description] = content[link.dataset.section];

    document.querySelector("#panel").innerHTML =
      `<h2>${title}</h2><p>${description}</p>`;

    document.querySelector("#panel").scrollIntoView({
      behavior: "smooth",
      block: "nearest"
    });
  });
});

// ==========================================
// PASTILLES ROUGES
// ==========================================

const categories = {
  "Équipes": "equipes",
  "Vidéos": "videos",
  "Facebook": "facebook",
  "WhatsApp": "whatsapp",
  "Compétitions": "calendrier",
  "Documents": "documents",
  "HelloAsso": "helloasso"
};

const menuLinks = [];

document.querySelectorAll(".menu .tile").forEach(link => {
  const label = link.querySelector("strong")?.textContent.trim();
  const category = categories[label];

  if (category) {
    menuLinks.push({ link, category });

    link.style.position = "relative";

    const dot = document.createElement("span");
    dot.className = "notification-dot";
    dot.setAttribute("aria-label", "Nouvelle information");
    dot.style.cssText = `
      display:none;
      position:absolute;
      top:9px;
      right:9px;
      width:12px;
      height:12px;
      background:#e52323;
      border:2px solid white;
      border-radius:50%;
      box-shadow:0 1px 4px rgba(0,0,0,.25);
    `;

    link.appendChild(dot);

    link.addEventListener("click", () => {
      marquerCommeLues(category);
    });
  }
});

let utilisateur = null;
let notificationsActives = [];
let lectures = new Set();

function actualiserPastilles() {
  menuLinks.forEach(({ link, category }) => {
    const nouvelles = notificationsActives.some(notification =>
      notification.category === category &&
      !lectures.has(notification.id)
    );

    const dot = link.querySelector(".notification-dot");

    if (dot) {
      dot.style.display = nouvelles ? "block" : "none";
    }
  });
}

// ==========================================
// LECTURES INDIVIDUELLES
// ==========================================

async function marquerCommeLues(category) {
  if (!utilisateur) return;

  const nouvelles = notificationsActives.filter(notification =>
    notification.category === category &&
    !lectures.has(notification.id)
  );

  for (const notification of nouvelles) {
    try {
      await db
        .collection("users")
        .doc(utilisateur.uid)
        .collection("reads")
        .doc(notification.id)
        .set({
          readAt: firebase.firestore.FieldValue.serverTimestamp()
        });

      lectures.add(notification.id);
    } catch (error) {
      console.error("Erreur d'enregistrement de lecture :", error);
    }
  }

  actualiserPastilles();
}

// ==========================================
// RÉCEPTION DES NOUVEAUTÉS FIRESTORE
// ==========================================

function ecouterNotifications() {
  db.collection("notifications").onSnapshot(snapshot => {
    notificationsActives = snapshot.docs.map(doc => ({
      id: doc.id,
      ...doc.data()
    }));

    actualiserPastilles();

  }, error => {
    console.error("Erreur notifications :", error);
  });

  db.collection("users")
    .doc(utilisateur.uid)
    .collection("reads")
    .onSnapshot(snapshot => {
      lectures = new Set(snapshot.docs.map(doc => doc.id));
      actualiserPastilles();

    }, error => {
      console.error("Erreur lectures :", error);
    });
}

// ==========================================
// IDENTIFICATION ANONYME DU TÉLÉPHONE
// ==========================================

auth.signInAnonymously()
  .then(async result => {
    utilisateur = result.user;

    await db.collection("users")
      .doc(utilisateur.uid)
      .set({
        updatedAt: firebase.firestore.FieldValue.serverTimestamp()
      }, { merge: true });

    ecouterNotifications();

  })
  .catch(error => {
    console.error("Erreur identification anonyme :", error);
  });

// ==========================================
// BOUTON D'ACTIVATION DES NOTIFICATIONS
// ==========================================

function ajouterBoutonNotifications() {
  const intro = document.querySelector(".intro");
  if (!intro) return;

  const bouton = document.createElement("button");

  bouton.textContent = "🔔 Activer les notifications";
  bouton.type = "button";

  bouton.style.cssText = `
    display:block;
    margin:12px auto 18px;
    padding:11px 18px;
    border:0;
    border-radius:10px;
    background:#102b55;
    color:white;
    font-size:15px;
    font-weight:bold;
    cursor:pointer;
  `;

  intro.insertAdjacentElement("afterend", bouton);

  bouton.addEventListener("click", activerNotifications);
}

async function activerNotifications() {
  const bouton = document.querySelector(".intro + button");

  try {
    if (!("Notification" in window)) {
      alert("Les notifications ne sont pas disponibles sur ce navigateur.");
      return;
    }

    const estInstallee =
      window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true;

    if (
      /iPhone|iPad|iPod/.test(navigator.userAgent) &&
      !estInstallee
    ) {
      alert("Sur iPhone, ajoute d'abord l'application à l'écran d'accueil, puis ouvre-la depuis son icône pour activer les notifications.");
      return;
    }

    if (!utilisateur) {
      alert("L'application est encore en cours de connexion. Réessaie dans quelques secondes.");
      return;
    }

    const permission = await Notification.requestPermission();

    if (permission !== "granted") {
      alert("Les notifications n'ont pas été autorisées.");
      return;
    }

    const supported = await firebase.messaging.isSupported();

    if (!supported) {
      alert("Ce navigateur ne prend pas en charge les notifications Firebase.");
      return;
    }

    const registration = await window.smttServiceWorkerRegistration;

    if (!registration) {
      throw new Error("Service worker indisponible.");
    }

    const messaging = firebase.messaging();

    const token = await messaging.getToken({
      vapidKey: VAPID_KEY,
      serviceWorkerRegistration: registration
    });

    if (!token) {
      throw new Error("Aucun jeton de notification reçu.");
    }

    await db.collection("users")
      .doc(utilisateur.uid)
      .set({
        fcmToken: token,
        notificationsEnabled: true,
        updatedAt: firebase.firestore.FieldValue.serverTimestamp()
      }, { merge: true });

    bouton.textContent = "✓ Notifications activées";
    alert("Les notifications sont activées sur cet appareil !");

  } catch (error) {
    console.error("Erreur activation notifications :", error);
    alert("Impossible d'activer les notifications. Consulte la console ou réessaie.");
  }
}

ajouterBoutonNotifications();
