from fastapi import FastAPI, UploadFile, File, Form, HTTPException
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
        "balance": 100.0,
        "listings": []
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

        if "balance" not in data:
            data["balance"] = 100.0

        if "listings" not in data:
            data["listings"] = []

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
# PAGE
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def home():

    if not HTML_FILE.exists():

        return HTMLResponse(
            "<h1>index.html introuvable</h1>",
            status_code=500
        )

    return HTML_FILE.read_text(
        encoding="utf-8"
    )


# ============================================================
# STATE
# ============================================================

@app.get("/api/state")
async def get_state():

    return {
        "balance": database["balance"],
        "listings": database["listings"]
    }


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

    name: str = Form(...),

    age: int = Form(...),

    location: str = Form(...),

    description: str = Form(...),

    baldness: int = Form(...),

    starting_price: float = Form(...),

    image: UploadFile | None = File(None)

):

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

        destination = (
            UPLOAD_DIR / filename
        )

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

        image_url = (
            f"/uploads/{filename}"
        )

    # ========================================================
    # ID
    # ========================================================

    listings = database["listings"]

    new_id = max(
        [
            int(x.get("id", 0))
            for x in listings
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

        "owner": "me"

    }

    listings.insert(
        0,
        new_listing
    )

    save_database(database)

    return {
        "success": True,
        "listing": new_listing
    }


# ============================================================
# BID
# ============================================================

@app.post("/api/bid/{listing_id}")
async def bid(

    listing_id: int,

    amount: float = Form(...)

):

    listing = next(
        (
            x for x in database["listings"]
            if int(x["id"]) == listing_id
        ),
        None
    )

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Annonce introuvable."
        )

    # Impossible d'enchérir sur son propre chauve
    if listing.get("owner") == "me":
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

    if amount > database["balance"]:

        raise HTTPException(
            status_code=400,
            detail=(
                f"Solde insuffisant. "
                f"Tu as seulement "
                f"{database['balance']:.2f} €."
            )
        )

    listing["price"] = amount

    listing["bids"] = (
        int(listing.get("bids", 0)) + 1
    )

    save_database(database)

    return {
        "success": True,
        "balance": database["balance"],
        "listing": listing
    }


# ============================================================
# BUY
# ============================================================

@app.post("/api/buy/{listing_id}")
async def buy(listing_id: int):

    listings = database["listings"]

    listing = next(
        (
            x for x in listings
            if int(x["id"]) == listing_id
        ),
        None
    )

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Annonce introuvable."
        )

    # ========================================================
    # PROPRE ANNONCE
    # ========================================================

    if listing.get("owner") == "me":

        raise HTTPException(
            status_code=400,
            detail=(
                "Tu ne peux pas acheter "
                "ton propre chauve."
            )
        )

    price = round(
        float(listing["price"]),
        2
    )

    balance = round(
        float(database["balance"]),
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

    database["balance"] = round(
        balance - price,
        2
    )

    database["listings"] = [
        x
        for x in listings
        if int(x["id"]) != listing_id
    ]

    save_database(database)

    return {
        "success": True,
        "balance": database["balance"],
        "listing": listing
    }


# ============================================================
# FAVICON
# ============================================================

@app.get("/favicon.ico")
async def favicon():
    return JSONResponse(content={})


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000
    )