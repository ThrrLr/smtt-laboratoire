import os
import json
import hashlib
import urllib.request
import xml.etree.ElementTree as ET

import firebase_admin
from firebase_admin import credentials, firestore, messaging

from google.oauth2 import service_account
from googleapiclient.discovery import build


# ==========================================
# CONFIGURATION
# ==========================================

FIREBASE_SERVICE_ACCOUNT = json.loads(
    os.environ["FIREBASE_SERVICE_ACCOUNT"]
)

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly"
]

DRIVE_SOURCES = [
    {
        "name": "Équipes",
        "category": "equipes",
        "folder_id": "1jVjRtxUFW16XcQiyBiWIJUwUuL2w70L_"
    },
    {
        "name": "Documents",
        "category": "documents",
        "folder_id": "14zQilGmblymrCXx2L_ZUDhvkyvHktzBp"
    },
    {
        "name": "Compétitions",
        "category": "calendrier",
        "file_id": "1PkxeVKZ1zbfUWRuQFZ5VYc06uEgDKwfJ"
    }
]

# Chaîne YouTube du Stade Montois TT
YOUTUBE_CHANNEL_ID = "UCUPOXsxa74oOcfkGrx079WQ"

YOUTUBE_FEED_URL = (
    "https://www.youtube.com/feeds/videos.xml?channel_id="
    + YOUTUBE_CHANNEL_ID
)

# Flux RSS Facebook (FetchRSS) du Stade Montois TT
FACEBOOK_FEED_URL = "https://fetchrss.com/feed/1xUlSA4LZE6M1xUlR77gK5bu.rss"
FACEBOOK_TOPIC = "smtt_actus"


# ==========================================
# CONNEXION FIREBASE
# ==========================================

firebase_credential = credentials.Certificate(
    FIREBASE_SERVICE_ACCOUNT
)

firebase_admin.initialize_app(firebase_credential)

db = firestore.client()


# ==========================================
# CONNEXION GOOGLE DRIVE
# ==========================================

drive_credential = service_account.Credentials.from_service_account_info(
    FIREBASE_SERVICE_ACCOUNT,
    scopes=DRIVE_SCOPES
)

drive = build(
    "drive",
    "v3",
    credentials=drive_credential,
    cache_discovery=False
)


# ==========================================
# RECHERCHE DES FICHIERS DRIVE
# ==========================================

def lire_dossier(folder_id, source_name, category):
    fichiers = []
    page_token = None

    while True:
        resultat = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id,name,mimeType,modifiedTime)",
            pageToken=page_token,
            pageSize=100
        ).execute()

        for fichier in resultat.get("files", []):

            if fichier["mimeType"] == "application/vnd.google-apps.folder":
                fichiers.extend(
                    lire_dossier(
                        fichier["id"],
                        source_name,
                        category
                    )
                )

            else:
                fichiers.append({
                    **fichier,
                    "source": source_name,
                    "category": category
                })

        page_token = resultat.get("nextPageToken")

        if not page_token:
            break

    return fichiers


def recuperer_toutes_les_sources():
    fichiers = []

    for source in DRIVE_SOURCES:

        if "folder_id" in source:
            fichiers.extend(
                lire_dossier(
                    source["folder_id"],
                    source["name"],
                    source["category"]
                )
            )

        else:
            fichier = drive.files().get(
                fileId=source["file_id"],
                fields="id,name,mimeType,modifiedTime"
            ).execute()

            fichiers.append({
                **fichier,
                "source": source["name"],
                "category": source["category"]
            })

    return fichiers


# ==========================================
# MÉMOIRE DES FICHIERS DÉJÀ SURVEILLÉS
# ==========================================

def base_drive_deja_initialisee():
    premier_doc = next(db.collection("drive_monitor").limit(1).stream(), None)
    return premier_doc is not None


def traiter_fichier(fichier, notifier_nouveaux=True):

    file_id = fichier["id"]
    modified_time = fichier.get("modifiedTime", "")

    state_id = hashlib.sha256(
        file_id.encode("utf-8")
    ).hexdigest()

    state_ref = db.collection("drive_monitor").document(state_id)

    notification_id = hashlib.sha256(
        f"{file_id}_{modified_time}".encode("utf-8")
    ).hexdigest()

    notification_ref = db.collection("notifications").document(
        notification_id
    )

    notification_data = {
        "category": fichier["category"],
        "title": "🏓 Stade Montois TT",
        "body": f"Nouvelle information dans {fichier['source']} : {fichier['name']}",
        "source": fichier["source"],
        "fileName": fichier["name"],
        "fileId": file_id,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "pushSent": False
    }

    @firestore.transactional
    def enregistrer(transaction):

        snapshot = state_ref.get(transaction=transaction)

        nouvel_etat = {
            "fileId": file_id,
            "name": fichier["name"],
            "modifiedTime": modified_time,
            "source": fichier["source"],
            "category": fichier["category"]
        }

        if not snapshot.exists:
            transaction.set(state_ref, nouvel_etat)
            if notifier_nouveaux:
                transaction.set(notification_ref, notification_data)
                return "nouveau"
            return "initialisation"

        ancien_etat = snapshot.to_dict()

        if (
            ancien_etat.get("modifiedTime") == modified_time
            and ancien_etat.get("name") == fichier["name"]
        ):
            return "inchangé"

        transaction.set(state_ref, nouvel_etat)
        transaction.set(notification_ref, notification_data)

        return "modifié"

    return enregistrer(db.transaction())


# ==========================================
# SURVEILLANCE YOUTUBE
# ==========================================

def surveiller_youtube():

    print("Surveillance YouTube SMTT démarrée.")

    try:
        requete = urllib.request.Request(
            YOUTUBE_FEED_URL,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        with urllib.request.urlopen(requete, timeout=20) as reponse:
            contenu = reponse.read()

        racine = ET.fromstring(contenu)

        atom = "{http://www.w3.org/2005/Atom}"
        yt = "{http://www.youtube.com/xml/schemas/2015}"

        videos = []

        for entree in racine.findall(atom + "entry"):

            video_id = entree.findtext(yt + "videoId")
            titre = entree.findtext(atom + "title")

            lien = entree.find(atom + "link")
            url = (
                lien.get("href")
                if lien is not None
                else f"https://www.youtube.com/watch?v={video_id}"
            )

            if video_id and titre:
                videos.append({
                    "id": video_id,
                    "title": titre,
                    "url": url
                })

        if not videos:
            print("Aucune vidéo trouvée dans le flux YouTube.")
            return

        etat_ref = db.collection("youtube_monitor").document(
            YOUTUBE_CHANNEL_ID
        )

        etat = etat_ref.get()

        # Premier passage : mémorisation des vidéos existantes.
        if not etat.exists:

            batch = db.batch()

            for video in videos:
                video_state_id = hashlib.sha256(
                    video["id"].encode("utf-8")
                ).hexdigest()

                video_ref = db.collection("youtube_seen").document(
                    video_state_id
                )

                batch.set(video_ref, {
                    "videoId": video["id"],
                    "title": video["title"],
                    "initialized": True
                })

            batch.set(etat_ref, {
                "initialized": True,
                "lastVideoId": videos[0]["id"]
            })

            batch.commit()

            print(
                len(videos),
                "vidéos existantes mémorisées sans notification."
            )

            return

        # Passages suivants : recherche des nouvelles vidéos.
        nouvelles = 0

        for video in reversed(videos):

            video_state_id = hashlib.sha256(
                video["id"].encode("utf-8")
            ).hexdigest()

            video_ref = db.collection("youtube_seen").document(
                video_state_id
            )

            if video_ref.get().exists:
                continue

            notification_id = hashlib.sha256(
                f"youtube_{video['id']}".encode("utf-8")
            ).hexdigest()

            notification_ref = db.collection(
                "notifications"
            ).document(notification_id)

            batch = db.batch()

            batch.set(video_ref, {
                "videoId": video["id"],
                "title": video["title"],
                "initialized": True
            })

            batch.set(notification_ref, {
                "category": "videos",
                "title": "🏓 Nouvelle vidéo SMTT",
                "body": f"Nouvelle vidéo sur la chaîne du club : {video['title']}",
                "source": "YouTube",
                "videoId": video["id"],
                "videoUrl": video["url"],
                "url": video["url"],
                "createdAt": firestore.SERVER_TIMESTAMP,
                "pushSent": False
            })

            batch.commit()

            nouvelles += 1

            print("Nouvelle vidéo détectée :", video["title"])

        batch = db.batch()
        batch.set(etat_ref, {
            "initialized": True,
            "lastVideoId": videos[0]["id"]
        }, merge=True)
        batch.commit()

        print(nouvelles, "nouvelle(s) vidéo(s) détectée(s).")

    except Exception as erreur:
        print("Erreur surveillance YouTube :", erreur)


# ==========================================
# SURVEILLANCE FACEBOOK (FETCHRSS)
# ==========================================

def surveiller_facebook():

    if not FACEBOOK_FEED_URL:
        print("Aucun flux Facebook configuré.")
        return

    print("Surveillance Facebook SMTT démarrée.")

    try:
        requete = urllib.request.Request(
            FACEBOOK_FEED_URL,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        with urllib.request.urlopen(requete, timeout=20) as reponse:
            contenu = reponse.read()

        racine = ET.fromstring(contenu)

        posts = []

        # Format RSS classique (<item>)
        for item in racine.findall(".//item"):
            guid = (item.findtext("guid") or "").strip()
            lien = (item.findtext("link") or "").strip()
            titre = (item.findtext("title") or "").strip()
            description = (item.findtext("description") or "").strip()

            identifiant = guid or lien or f"{titre}_{description[:80]}"
            resume = titre or description[:100] or "Nouvelle publication Facebook du club."

            if identifiant:
                posts.append({
                    "id": identifiant,
                    "title": "🏓 Actualité Facebook SMTT",
                    "body": resume,
                    "url": lien or "https://www.facebook.com"
                })

        # Repli format Atom (<entry>) si nécessaire
        if not posts:
            atom = "{http://www.w3.org/2005/Atom}"
            for entry in racine.findall(f"{atom}entry"):
                entry_id = (entry.findtext(f"{atom}id") or "").strip()
                titre = (entry.findtext(f"{atom}title") or "").strip()
                lien_elem = entry.find(f"{atom}link")
                lien = (lien_elem.get("href") if lien_elem is not None else "") or ""
                identifiant = entry_id or lien or titre
                if identifiant:
                    posts.append({
                        "id": identifiant,
                        "title": "🏓 Actualité Facebook SMTT",
                        "body": titre or "Nouvelle publication Facebook du club.",
                        "url": lien or "https://www.facebook.com"
                    })

        if not posts:
            print("Aucune publication trouvée dans le flux Facebook.")
            return

        etat_id = hashlib.sha256(
            FACEBOOK_FEED_URL.encode("utf-8")
        ).hexdigest()

        etat_ref = db.collection("facebook_monitor").document(etat_id)
        etat = etat_ref.get()

        # Premier passage : mémorisation des publications existantes sans notifier.
        if not etat.exists:
            batch = db.batch()

            for post in posts:
                post_hash = hashlib.sha256(
                    post["id"].encode("utf-8")
                ).hexdigest()

                post_ref = db.collection("facebook_seen").document(post_hash)
                batch.set(post_ref, {
                    "postId": post["id"],
                    "url": post["url"],
                    "initialized": True
                })

            batch.set(etat_ref, {
                "initialized": True,
                "lastPostId": posts[0]["id"]
            })

            batch.commit()
            print(
                len(posts),
                "publications Facebook existantes mémorisées sans notification."
            )
            return

        # Passages suivants : détection des nouvelles publications.
        nouvelles = 0

        for post in reversed(posts):
            post_hash = hashlib.sha256(
                post["id"].encode("utf-8")
            ).hexdigest()

            post_ref = db.collection("facebook_seen").document(post_hash)
            if post_ref.get().exists:
                continue

            notification_id = hashlib.sha256(
                f"facebook_{post['id']}".encode("utf-8")
            ).hexdigest()

            notification_ref = db.collection("notifications").document(
                notification_id
            )

            batch = db.batch()
            batch.set(post_ref, {
                "postId": post["id"],
                "url": post["url"],
                "initialized": True
            })

            batch.set(notification_ref, {
                "category": "facebook",
                "title": post["title"],
                "body": post["body"],
                "source": "Facebook",
                "url": post["url"],
                "appUrl": post["url"],
                "createdAt": firestore.SERVER_TIMESTAMP,
                "pushSent": False
            })

            batch.commit()
            nouvelles += 1
            print("Nouvelle publication Facebook détectée :", post["body"])

        batch = db.batch()
        batch.set(etat_ref, {
            "initialized": True,
            "lastPostId": posts[0]["id"]
        }, merge=True)
        batch.commit()

        print(nouvelles, "nouvelle(s) publication(s) Facebook détectée(s).")

    except Exception as erreur:
        print("Erreur surveillance Facebook :", erreur)


# ==========================================
# ABONNEMENT AUTOMATIQUE AU SUJET smtt_actus
# ==========================================

def abonner_tokens_au_topic(tokens):

    if not tokens or not FACEBOOK_TOPIC:
        return

    # Suppression des doublons tout en gardant l'ordre
    tokens_uniques = list(dict.fromkeys(tokens))

    # Firebase accepte jusqu'à 1000 tokens par appel
    taille_lot = 1000
    total_abonnes = 0

    for i in range(0, len(tokens_uniques), taille_lot):
        lot = tokens_uniques[i:i + taille_lot]
        try:
            reponse = messaging.subscribe_to_topic(lot, FACEBOOK_TOPIC)
            total_abonnes += getattr(reponse, "success_count", len(lot))
        except Exception as erreur:
            print(f"Erreur abonnement au topic {FACEBOOK_TOPIC} :", erreur)

    print(
        f"Synchronisation topic '{FACEBOOK_TOPIC}' terminée ({total_abonnes} jeton(s) traité(s))."
    )


# ==========================================
# ENVOI DES NOTIFICATIONS AUX IPHONES
# ==========================================

def envoyer_notifications_en_attente():

    utilisateurs = db.collection("users").stream()

    tokens = []

    for utilisateur in utilisateurs:
        donnees = utilisateur.to_dict()

        if (
            donnees.get("notificationsEnabled") is True
            and donnees.get("fcmToken")
        ):
            tokens.append(donnees["fcmToken"])

    if not tokens:
        print("Aucun téléphone avec notifications activées.")
        return

    # Abonne automatiquement tous les jetons actifs au sujet smtt_actus
    abonner_tokens_au_topic(tokens)

    notifications = db.collection("notifications").where(
        "pushSent", "==", False
    ).stream()

    for notification in notifications:

        donnees = notification.to_dict()

        titre = str(
            donnees.get("title", "Stade Montois TT")
        )

        corps = str(
            donnees.get(
                "body",
                "Une nouvelle information est disponible."
            )
        )

        lien_cible = str(
            donnees.get("url")
            or donnees.get("appUrl")
            or donnees.get("videoUrl")
            or "https://thrrlr.github.io/smtt/"
        )

        message_data = {
            "title": titre,
            "body": corps,
            "category": str(donnees.get("category", "")),
            "notificationId": notification.id,
            "url": lien_cible,
            "appUrl": lien_cible
        }

        nombre_envoye = 0

        for token in tokens:
            try:
                message = messaging.Message(
                    notification=messaging.Notification(
                        title=titre,
                        body=corps
                    ),
                    data=message_data,
                    token=token,
                    webpush=messaging.WebpushConfig(
                        headers={
                            "Urgency": "high"
                        },
                        notification=messaging.WebpushNotification(
                            icon="https://thrrlr.github.io/smtt/icons/icon.svg"
                        ),
                        fcm_options=messaging.WebpushFCMOptions(
                            link=lien_cible
                        )
                    )
                )

                resultat = messaging.send(message)

                nombre_envoye += 1

                print(
                    "Push accepté par Firebase :",
                    resultat
                )

            except Exception as erreur:
                print("Erreur envoi notification :", erreur)

        if nombre_envoye > 0:
            notification.reference.update({
                "pushSent": True
            })

            print(
                "Notification envoyée :",
                corps
            )


# ==========================================
# PROGRAMME PRINCIPAL
# ==========================================

def main():

    print("Surveillance Google Drive SMTT démarrée.")

    notifier_nouveaux = base_drive_deja_initialisee()

    fichiers = recuperer_toutes_les_sources()

    print(len(fichiers), "fichiers trouvés.")

    for fichier in fichiers:

        resultat = traiter_fichier(
            fichier,
            notifier_nouveaux=notifier_nouveaux
        )

        print(
            fichier["source"],
            "-",
            fichier["name"],
            ":",
            resultat
        )

    surveiller_youtube()

    surveiller_facebook()

    envoyer_notifications_en_attente()

    print("Surveillance terminée.")


if __name__ == "__main__":
    main()
