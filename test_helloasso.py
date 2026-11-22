
import os
import json
import urllib.request
import urllib.parse
import urllib.error

CLIENT_ID = os.environ["HELLOASSO_CLIENT_ID"]
CLIENT_SECRET = os.environ["HELLOASSO_CLIENT_SECRET"]

ORGANIZATION = "stade-montois-omnisports-tennis-de-table"

def main():
    print("1. Connexion à HelloAsso...")

    token_url = "https://api.helloasso.com/oauth2/token"

    token_data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }).encode()

    request = urllib.request.Request(
        token_url,
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        tokens = json.loads(response.read().decode())

    access_token = tokens.get("access_token")

    if not access_token:
        raise Exception("Aucun jeton d'accès reçu.")

    print("Connexion réussie.")
    print("Jeton d'accès reçu :", True)
    print("Jeton de renouvellement reçu :", bool(tokens.get("refresh_token")))

    print("\n2. Recherche des formulaires du club...")

    params = urllib.parse.urlencode({
        "states": "Public",
        "pageIndex": 1,
        "pageSize": 10
    })

    url = (
        "https://api.helloasso.com/v5/organizations/"
        + ORGANIZATION
        + "/forms?"
        + params
    )

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + access_token,
            "Accept": "application/json"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode())

    print("Réponse HelloAsso reçue.")
    print("Type de réponse :", type(result).__name__)

    if isinstance(result, dict):
        print("Champs reçus :", list(result.keys()))

        forms = result.get("data", [])
        if isinstance(forms, list):
            print("Nombre de formulaires trouvés :", len(forms))

            for form in forms:
                if isinstance(form, dict):
                    name = (
                        form.get("formName")
                        or form.get("name")
                        or "Nom non identifié"
                    )
                    print("- ", name)
        else:
            print("Structure des formulaires à examiner.")

    elif isinstance(result, list):
        print("Nombre de formulaires trouvés :", len(result))
        for form in result:
            if isinstance(form, dict):
                print("- ", form.get("formName", "Nom non identifié"))

    print("\nTEST TERMINÉ.")

if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        print("ERREUR HTTP :", error.code)
        print(error.read().decode()[:1000])
        raise
    except Exception as error:
        print("ERREUR :", str(error))
        raise
