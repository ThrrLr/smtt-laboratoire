
import os
import json
import firebase_admin

from firebase_admin import credentials, firestore, messaging

# Connexion sécurisée à Firebase
service_account = json.loads(
    os.environ["FIREBASE_SERVICE_ACCOUNT"]
)

cred = credentials.Certificate(service_account)
firebase_admin.initialize_app(cred)

db = firestore.client()

# Identification du téléphone de test
test_uid = os.environ["TEST_UID"]

user = db.collection("users").document(test_uid).get()

if not user.exists:
    raise Exception("Utilisateur de test introuvable")

token = user.to_dict().get("fcmToken")

if not token:
    raise Exception("Aucun téléphone enregistré pour cet utilisateur")

# Notification de test
message = messaging.Message(
    notification=messaging.Notification(
        title="🏓 Stade Montois TT",
        body="Bravo ! Les notifications SMTT fonctionnent."
    ),
    data={
        "category": "videos",
        "test": "true"
    },
    token=token
)

response = messaging.send(message)

print("Notification envoyée avec succès :", response)
