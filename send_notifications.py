
import os
import json
import hashlib
import urllib.request
import urllib.error
import urllib.parse
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

# Facebook : API Graph Meta
FACEBOOK_PAGE_ID = "1091094834343855"
FACEBOOK_PAGE_ACCESS_TOKEN = os.environ.get(
    "FACEBOOK_PAGE_ACCESS_TOKEN", ""
).strip()
FACEBOOK_GRAPH_API_VERSION = "v27.0"
FACEBOOK_TOPIC = "smtt_actus"

# Page HelloAsso du Stade Montois TT + Google Sheet CSV (ligne 5 = A5)
HELLOASSO_URL = "https://www.helloasso.com/associations/stade-montois-omnisports-tennis-de-table"
HELLOASSO_SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vROcLSItSbZn-h5tLyorTcCdS7IL6EuLbuzwnEHHez7HeFrzoFg-Hmvg6lodTbkKQdy5_s_t2xQPtpl"
    "/pub?output=csv"
)


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
# SURVEILLANCE FACEBOOK (API GRAPH META)
# ==========================================

def surveiller_facebook():

    if not FACEBOOK_PAGE_ACCESS_TOKEN:
        print(
            "Erreur Facebook : le secret "
            "FACEBOOK_PAGE_ACCESS_TOKEN est absent."
        )
        return

    print("Surveillance Facebook SMTT via Meta démarrée.")

    try:
        parametres = urllib.parse.urlencode({
            "fields": "id,message,created_time,permalink_url,is_published",
            "limit": 25
        })

        url_api = (
            f"https://graph.facebook.com/"
            f"{FACEBOOK_GRAPH_API_VERSION}/"
            f"{FACEBOOK_PAGE_ID}/feed?{parametres}"
        )

        requete = urllib.request.Request(
            url_api,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Authorization": (
                    "Bearer " + FACEBOOK_PAGE_ACCESS_TOKEN
                )
            }
        )

        with urllib.request.urlopen(requete, timeout=30) as reponse:
            resultat_api = json.loads(
                reponse.read().decode("utf-8")
            )

        publications = resultat_api.get("data", [])
        posts = []

        for publication in publications:

            identifiant = str(publication.get("id") or "").strip()

            if not identifiant:
                continue

            if publication.get("is_published") is False:
                continue

            message = str(
                publication.get("message") or ""
            ).strip()

            resume = (
                message[:180]
                if message
                else "Nouvelle publication Facebook du club."
            )

            lien = str(
                publication.get("permalink_url") or ""
            ).strip()

            if not lien:
                lien = (
                    "https://www.facebook.com/"
                    + identifiant
                )

            posts.append({
                "id": identifiant,
                "title": "🏓 Actualité Facebook SMTT",
                "body": resume,
                "url": lien,
                "created_time": publication.get("created_time", "")
            })

        if not posts:
            print(
                "Aucune publication Facebook trouvée dans la réponse Meta."
            )
            return

        # Identifiant distinct de l'ancien suivi FetchRSS.
        etat_ref = db.collection("facebook_monitor").document(
            "meta_" + FACEBOOK_PAGE_ID
        )

        etat = etat_ref.get()

        # Premier passage : mémorisation des publications existantes
        # sans envoyer de notification.
        if not etat.exists:

            batch = db.batch()

            for post in posts:

                post_hash = hashlib.sha256(
                    ("meta_" + post["id"]).encode("utf-8")
                ).hexdigest()

                post_ref = db.collection("facebook_seen").document(
                    post_hash
                )

                batch.set(post_ref, {
                    "postId": post["id"],
                    "url": post["url"],
                    "createdTime": post["created_time"],
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
                ("meta_" + post["id"]).encode("utf-8")
            ).hexdigest()

            post_ref = db.collection("facebook_seen").document(
                post_hash
            )

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
                "createdTime": post["created_time"],
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

            print(
                "Nouvelle publication Facebook détectée :",
                post["body"]
            )

        batch = db.batch()
        batch.set(etat_ref, {
            "initialized": True,
            "lastPostId": posts[0]["id"]
        }, merge=True)
        batch.commit()

        print(
            nouvelles,
            "nouvelle(s) publication(s) Facebook détectée(s)."
        )

    except urllib.error.HTTPError as erreur:

        # Ne jamais afficher l'URL complète ni le jeton d'accès.
        try:
            details = json.loads(
                erreur.read().decode("utf-8")
            )
            message_erreur = (
                details.get("error", {}).get("message")
                or "Erreur renvoyée par Meta."
            )
        except Exception:
            message_erreur = "Réponse d'erreur illisible de Meta."

        print(
            "Erreur API Facebook HTTP",
            erreur.code,
            ":",
            message_erreur
        )

    except Exception as erreur:
        print("Erreur surveillance Facebook :", str(erreur))


# ==========================================
# SURVEILLANCE HELLOASSO (VIA GOOGLE SHEET CSV)
# ==========================================

def surveiller_helloasso():

    print("Surveillance HelloAsso SMTT démarrée.")

    try:
        requete = urllib.request.Request(
            HELLOASSO_SHEET_CSV_URL,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        with urllib.request.urlopen(requete, timeout=20) as reponse:
            texte_csv = reponse.read().decode("utf-8", errors="ignore")

        lignes = texte_csv.splitlines()
        texte_stage = ""

        # On regarde la ligne 5 (index 4), cellule A5
        if len(lignes) > 4:
            premiere_colonne = lignes[4].split(",")[0]
            texte_stage = premiere_colonne.strip().strip('"').strip()

        etat_ref = db.collection("helloasso_monitor").document("stage_alerte")
        etat = etat_ref.get()

        # Premier passage : mémorisation de l'état initial sans notifier.
        if not etat.exists:
            etat_ref.set({
                "initialized": True,
                "lastValue": texte_stage
            })
            print("État initial HelloAsso mémorisé sans notification.")
            return

        ancienne_valeur = str((etat.to_dict() or {}).get("lastValue") or "").strip()

        if texte_stage and texte_stage != ancienne_valeur:
            notification_id = hashlib.sha256(
                f"helloasso_{texte_stage}".encode("utf-8")
            ).hexdigest()

            db.collection("notifications").document(notification_id).set({
                "category": "helloasso",
                "title": "🏓 Nouveau stage HelloAsso SMTT",
                "body": texte_stage,
                "source": "HelloAsso",
                "url": HELLOASSO_URL,
                "appUrl": HELLOASSO_URL,
                "createdAt": firestore.SERVER_TIMESTAMP,
                "pushSent": False
            })

            etat_ref.set({
                "initialized": True,
                "lastValue": texte_stage
            }, merge=True)

            print("Nouveau stage HelloAsso détecté :", texte_stage)
        else:
            etat_ref.set({
                "initialized": True,
                "lastValue": texte_stage
            }, merge=True)
            print("Aucun nouveau stage HelloAsso détecté.")

    except Exception as erreur:
        print("Erreur surveillance HelloAsso :", erreur)


# ==========================================
# ABONNEMENT OPTIONNEL AU SUJET smtt_actus
# ==========================================

def abonner_tokens_au_topic(tokens):

    if not tokens or not FACEBOOK_TOPIC:
        return

    tokens_uniques = list(dict.fromkeys(tokens))
    taille_lot = 1000
    total_abonnes = 0

    for i in range(0, len(tokens_uniques), taille_lot):
        lot = tokens_uniques[i:i + taille_lot]
        try:
            reponse = messaging.subscribe_to_topic(lot, FACEBOOK_TOPIC)
            succes = getattr(reponse, "success_count", 0)
            total_abonnes += succes
        except Exception as erreur:
            print(f"Info topic {FACEBOOK_TOPIC} :", erreur)

    print(
        f"Synchronisation topic '{FACEBOOK_TOPIC}' terminée ({total_abonnes}/{len(tokens_uniques)} abonné(s) via topic)."
    )


# ==========================================
# ENVOI DES NOTIFICATIONS AUX IPHONES
# ==========================================

def envoyer_notifications_en_attente():

    utilisateurs = db.collection("users").stream()

    tokens = []

    for utilisateur in utilisateurs:
        donnees = utilisateur.to_dict() or {}

        notif_activee = donnees.get("notificationsEnabled") is True
        jeton = str(donnees.get("fcmToken") or "").strip()

        if notif_activee and jeton:
            tokens.append(jeton)

    if not tokens:
        print("Aucun téléphone avec notifications activées.")
        return

    print(f"{len(tokens)} jeton(s) actif(s) trouvé(s) dans Firestore.")
    abonner_tokens_au_topic(tokens)

    notifications = db.collection("notifications").where(
        "pushSent", "==", False
    ).stream()

    en_attente = list(notifications)
    print(f"{len(en_attente)} notification(s) en attente d'envoi.")

    for notification in en_attente:

        donnees = notification.to_dict() or {}

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
                            "Urgency": "high",
                            "TTL": "86400"
                        },
                        notification=messaging.WebpushNotification(
                            title=titre,
                            body=corps
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

    surveiller_helloasso()

    envoyer_notifications_en_attente()

    print("Surveillance terminée.")


if __name__ == "__main__":
    main()
