

import os
import json
import hashlib

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

def traiter_fichier(fichier):

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

        # Première découverte : mémorisation sans notification.
        if not snapshot.exists:
            transaction.set(state_ref, nouvel_etat)
            return "initialisation"

        ancien_etat = snapshot.to_dict()

        if (
            ancien_etat.get("modifiedTime") == modified_time
            and ancien_etat.get("name") == fichier["name"]
        ):
            return "inchangé"

        # Fichier modifié : mémorisation et création de la notification.
        transaction.set(state_ref, nouvel_etat)
        transaction.set(notification_ref, notification_data)

        return "modifié"

    return enregistrer(db.transaction())


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

    notifications = db.collection("notifications").where(
        "pushSent", "==", False
    ).stream()

    for notification in notifications:

        donnees = notification.to_dict()

        message_data = {
            "title": str(donnees.get("title", "Stade Montois TT")),
            "body": str(donnees.get("body", "Une nouvelle information est disponible.")),
            "category": str(donnees.get("category", "")),
            "notificationId": notification.id
        }

        nombre_envoye = 0

        for token in tokens:
            try:
                message = messaging.Message(
                    data=message_data,
                    token=token
                )

                messaging.send(message)
                nombre_envoye += 1

            except Exception as erreur:
                print("Erreur envoi notification :", erreur)

        if nombre_envoye > 0:
            notification.reference.update({
                "pushSent": True
            })

            print(
                "Notification envoyée :",
                donnees.get("body", "")
            )


# ==========================================
# PROGRAMME PRINCIPAL
# ==========================================

def main():

    print("Surveillance Google Drive SMTT démarrée.")

    fichiers = recuperer_toutes_les_sources()

    print(len(fichiers), "fichiers trouvés.")

    for fichier in fichiers:

        resultat = traiter_fichier(fichier)

        print(
            fichier["source"],
            "-",
            fichier["name"],
            ":",
            resultat
        )

    envoyer_notifications_en_attente()

    print("Surveillance terminée.")


if __name__ == "__main__":
    main()
