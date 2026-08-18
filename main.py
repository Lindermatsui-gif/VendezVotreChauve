from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pathlib import Path
import shutil
import uuid
import json
import uvicorn


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

HTML_FILE = BASE_DIR / "index.html"
UPLOAD_DIR = BASE_DIR / "uploads"
DATABASE_FILE = BASE_DIR / "database.json"

UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="VendezVotreChauve")


# ============================================================
# DATABASE
# ============================================================

def default_database():
    return {
        "accounts": {}
    }


def save_database(data):
    temp_file = DATABASE_FILE.with_suffix(".tmp")

    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            indent=4,
            ensure_ascii=False
        )

    temp_file.replace(DATABASE_FILE)


def load_database():

    if not DATABASE_FILE.exists():
        data = default_database()
        save_database(data)
        return data

    try:

        with open(
            DATABASE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError("Database invalide")

        if "accounts" not in data:
            data["accounts"] = {}

        return data

    except Exception as error:

        print(
            "Erreur database.json :",
            error
        )

        data = default_database()

        save_database(data)

        return data


database = load_database()


# ============================================================
# ACCOUNT
# ============================================================

def create_account():

    account_id = uuid.uuid4().hex

    database["accounts"][account_id] = {
        "balance": 100.0,
        "listings": []
    }

    save_database(database)

    return account_id


def get_account(request: Request):

    account_id = request.cookies.get("vvchauve_account")

    if not account_id:
        account_id = create_account()

        return account_id, database["accounts"][account_id], True

    if account_id not in database["accounts"]:

        database["accounts"][account_id] = {
            "balance": 100.0,
            "listings": []
        }

        save_database(database)

    return account_id, database["accounts"][account_id], False


def set_account_cookie(response, request: Request, account_id: str):
    """
    Pose le cookie de session.

    BUG CORRIGÉ : `secure` était codé en dur à True. Or un cookie
    "secure" n'est JAMAIS enregistré par le navigateur tant que la
    page n'est pas servie en https://. En local (http://localhost)
    ou derrière un déploiement sans HTTPS, le cookie ne survivait
    donc jamais à la requête suivante : un nouveau compte (et donc
    un nouveau solde de 100 €, avec toutes les annonces "perdues")
    était recréé à chaque rechargement de page.

    On calcule maintenant `secure` dynamiquement à partir du protocole
    réel de la requête : True en https, False en http.
    """

    response.set_cookie(
        key="vvchauve_account",
        value=account_id,
        max_age=60 * 60 * 24 * 365 * 5,
        httponly=True,
        samesite="lax",
        secure=(request.url.scheme == "https"),
    )


# ============================================================
# LISTINGS HELPERS
# ============================================================

def get_all_listings():
    """
    Renvoie TOUTES les annonces de TOUS les comptes (en copies), des
    plus récentes aux plus anciennes.

    BUG CORRIGÉ : /api/state ne renvoyait avant que les annonces du
    compte courant (`account["listings"]`). Résultat : personne ne
    pouvait jamais voir les annonces publiées par un autre compte, donc
    il était structurellement impossible d'enchérir ou d'acheter quoi
    que ce soit. Le frontend "cachait" même ce bug en forçant
    `owner = "me"` sur tout ce qu'il recevait, ce qui désactivait alors
    tous les boutons d'enchère/achat puisque tout semblait t'appartenir.
    """

    all_listings = []

    for acc in database["accounts"].values():
        for item in acc["listings"]:
            all_listings.append(dict(item))

    all_listings.sort(
        key=lambda item: int(item.get("id", 0)),
        reverse=True
    )

    return all_listings


def apply_featured(listings_list, top_count=3):
    """
    Calcule dynamiquement les annonces "en vedette" (priorité aux plus
    enchéries, puis aux plus chères). Rien n'est jamais réécrit en
    base : le champ "featured" n'existe que dans la réponse envoyée.

    BUG CORRIGÉ : "featured" restait toujours à False à la création et
    rien ne le passait jamais à True nulle part dans le code. La
    section "Chauves en vedette" du site était donc condamnée à rester
    vide en permanence, quoi qu'il arrive.
    """

    if not listings_list:
        return listings_list

    ranked = sorted(
        listings_list,
        key=lambda item: (
            int(item.get("bids", 0)),
            float(item.get("price", 0))
        ),
        reverse=True
    )

    featured_ids = {
        item["id"]
        for item in ranked[:top_count]
    }

    for item in listings_list:
        item["featured"] = item["id"] in featured_ids

    return listings_list


# ============================================================
# PAGE
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):

    if not HTML_FILE.exists():

        return HTMLResponse(
            "<h1>index.html introuvable</h1>",
            status_code=500
        )

    account_id, account, new_account = get_account(request)

    html = HTML_FILE.read_text(
        encoding="utf-8"
    )

    response = HTMLResponse(html)

    if new_account:
        set_account_cookie(response, request, account_id)

    return response


# ============================================================
# ACCOUNT API
# ============================================================

@app.get("/api/account")
async def get_account_api(request: Request):

    account_id, account, new_account = get_account(request)

    response = JSONResponse({
        "success": True,
        "account_id": account_id,
        "balance": account["balance"],
        "listings": account["listings"]
    })

    if new_account:
        set_account_cookie(response, request, account_id)

    return response


# ============================================================
# LOGOUT / NEW ACCOUNT
# ============================================================

@app.post("/api/account/new")
async def new_account(request: Request):

    account_id = create_account()

    response = JSONResponse({
        "success": True
    })

    set_account_cookie(response, request, account_id)

    return response


# ============================================================
# STATE
# ============================================================

@app.get("/api/state")
async def get_state(request: Request):

    account_id, account, new_account = get_account(request)

    all_listings = get_all_listings()
    apply_featured(all_listings)

    response = JSONResponse({
        "account_id": account_id,
        "balance": account["balance"],
        "listings": all_listings
    })

    if new_account:
        set_account_cookie(response, request, account_id)

    return response


# ============================================================
# IMAGES
# ============================================================

@app.get("/uploads/{filename}")
async def uploaded_file(filename: str):

    file_path = UPLOAD_DIR / filename

    if not file_path.exists():

        raise HTTPException(
            status_code=404,
            detail="Image introuvable"
        )

    return FileResponse(file_path)


# ============================================================
# CREATE LISTING
# ============================================================

@app.post("/api/listings")
async def create_listing(

    request: Request,

    name: str = Form(...),
    age: int = Form(...),
    location: str = Form(...),
    description: str = Form(...),
    baldness: int = Form(...),
    starting_price: float = Form(...),
    image: UploadFile | None = File(None)

):

    account_id, account, new_account = get_account(request)

    name = name.strip()
    location = location.strip()
    description = description.strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Le nom est obligatoire."
        )

    if not location:
        raise HTTPException(
            status_code=400,
            detail="La ville est obligatoire."
        )

    if not description:
        raise HTTPException(
            status_code=400,
            detail="La description est obligatoire."
        )

    if age < 18:
        raise HTTPException(
            status_code=400,
            detail="L'âge minimum est de 18 ans."
        )

    if age > 120:
        raise HTTPException(
            status_code=400,
            detail="Âge invalide."
        )

    if baldness < 0 or baldness > 100:
        raise HTTPException(
            status_code=400,
            detail="La calvitie doit être entre 0 et 100%."
        )

    if starting_price < 1:
        raise HTTPException(
            status_code=400,
            detail="Le prix doit être supérieur à 0€."
        )

    if starting_price > 1000000:
        raise HTTPException(
            status_code=400,
            detail="Prix trop élevé."
        )


    # ========================================================
    # IMAGE
    # ========================================================

    image_url = None

    if image and image.filename:

        extension = Path(
            image.filename
        ).suffix.lower()

        allowed = {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp"
        }

        if extension not in allowed:

            raise HTTPException(
                status_code=400,
                detail="Format d'image non supporté."
            )

        filename = (
            f"{uuid.uuid4().hex}"
            f"{extension}"
        )

        destination = UPLOAD_DIR / filename

        try:

            with destination.open("wb") as buffer:

                shutil.copyfileobj(
                    image.file,
                    buffer
                )

        except Exception as error:

            print(
                "Erreur upload :",
                error
            )

            raise HTTPException(
                status_code=500,
                detail="Impossible d'enregistrer l'image."
            )

        image_url = f"/uploads/{filename}"


    # ========================================================
    # ID
    # ========================================================

    all_listings = get_all_listings()

    new_id = max(
        [
            int(x.get("id", 0))
            for x in all_listings
        ],
        default=0
    ) + 1


    # ========================================================
    # LISTING
    # ========================================================

    new_listing = {

        "id": new_id,

        "name": name,

        "age": age,

        "location": location,

        "baldness": baldness,

        "description": description,

        "price": round(
            float(starting_price),
            2
        ),

        "bids": 0,

        "time": "24h 00m",

        "featured": False,

        "image": image_url,

        "owner": account_id

    }


    account["listings"].insert(
        0,
        new_listing
    )

    save_database(database)


    response = JSONResponse({
        "success": True,
        "listing": new_listing
    })


    if new_account:
        set_account_cookie(response, request, account_id)

    return response


# ============================================================
# BID
# ============================================================

@app.post("/api/bid/{listing_id}")
async def bid(

    request: Request,

    listing_id: int,

    amount: float = Form(...)

):

    account_id, account, new_account = get_account(request)


    # Cherche dans tous les comptes
    listing = None
    owner_account = None

    for owner_id, acc in database["accounts"].items():

        for item in acc["listings"]:

            if int(item["id"]) == listing_id:

                listing = item
                owner_account = acc
                break

        if listing:
            break


    if listing is None:

        raise HTTPException(
            status_code=404,
            detail="Annonce introuvable."
        )


    if listing.get("owner") == account_id:

        raise HTTPException(
            status_code=400,
            detail="Tu ne peux pas enchérir sur ton propre chauve."
        )


    amount = round(
        float(amount),
        2
    )

    current_price = round(
        float(listing["price"]),
        2
    )


    if amount <= current_price:

        raise HTTPException(
            status_code=400,
            detail=(
                f"L'enchère doit être supérieure "
                f"à {current_price:.2f} €."
            )
        )


    if amount > account["balance"]:

        raise HTTPException(
            status_code=400,
            detail=(
                f"Solde insuffisant. "
                f"Tu as seulement "
                f"{account['balance']:.2f} €."
            )
        )


    listing["price"] = amount

    listing["bids"] = (
        int(listing.get("bids", 0)) + 1
    )

    save_database(database)


    response = JSONResponse({
        "success": True,
        "balance": account["balance"],
        "listing": listing
    })

    if new_account:
        set_account_cookie(response, request, account_id)

    return response


# ============================================================
# BUY
# ============================================================

@app.post("/api/buy/{listing_id}")
async def buy(

    request: Request,

    listing_id: int

):

    account_id, account, new_account = get_account(request)


    listing = None
    seller_account = None


    for owner_id, acc in database["accounts"].items():

        for item in acc["listings"]:

            if int(item["id"]) == listing_id:

                listing = item
                seller_account = acc

                break

        if listing:
            break


    if listing is None:

        raise HTTPException(
            status_code=404,
            detail="Annonce introuvable."
        )


    if listing.get("owner") == account_id:

        raise HTTPException(
            status_code=400,
            detail="Tu ne peux pas acheter ton propre chauve."
        )


    price = round(
        float(listing["price"]),
        2
    )

    balance = round(
        float(account["balance"]),
        2
    )


    if price > balance:

        raise HTTPException(
            status_code=400,
            detail=(
                f"Solde insuffisant. "
                f"Prix : {price:.2f} € | "
                f"Solde : {balance:.2f} €"
            )
        )


    # ========================================================
    # TRANSACTION
    # ========================================================

    account["balance"] = round(
        balance - price,
        2
    )


    # Le vendeur récupère l'argent
    seller_account["balance"] = round(
        float(seller_account["balance"]) + price,
        2
    )


    seller_account["listings"] = [
        x
        for x in seller_account["listings"]
        if int(x["id"]) != listing_id
    ]


    # BUG CORRIGÉ : l'acheteur ne récupérait jamais l'annonce achetée.
    # Elle disparaissait juste du site sans jamais apparaître dans "Mes
    # chauves" côté acheteur, ce qui rendait la revente impossible.
    # Maintenant l'acheteur devient le nouveau propriétaire.
    listing["owner"] = account_id
    listing["bids"] = 0
    listing["time"] = "24h 00m"

    account["listings"].insert(0, listing)


    save_database(database)


    response = JSONResponse({
        "success": True,
        "balance": account["balance"],
        "listing": listing
    })

    if new_account:
        set_account_cookie(response, request, account_id)

    return response


# ============================================================
# FAVICON
# ============================================================

@app.get("/favicon.ico")
async def favicon():

    return JSONResponse(
        content={}
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000
    )