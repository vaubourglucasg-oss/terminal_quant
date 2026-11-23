"""Routes de gestion des données personnelles de l'utilisateur connecté :
- Préférences d'affichage, filtres et réglages graphiques (/api/user/preferences)
- Watchlist / Favoris (/api/user/favorites)

Toutes les données sont strictement cloisonnées par user_id dans users.db.
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from app.api.auth_routes import require_login
from app.engine.auth import (obtenir_preferences, sauvegarder_preferences,
                             obtenir_favoris, ajouter_favori, supprimer_favori, definir_favoris)

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/preferences")
async def lire_preferences(user: dict = Depends(require_login)):
    """Récupère les paramètres et réglages de l'utilisateur connecté."""
    prefs = obtenir_preferences(user["id"])
    return {"status": "ok", "user_id": user["id"], "preferences": prefs}


@router.post("/preferences")
async def enregistrer_preferences(request: Request, user: dict = Depends(require_login)):
    """Sauvegarde les préférences (affichage, colonnes, filtres, hypothèses, graphique)."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Corps JSON invalide")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Un objet JSON est attendu")

    sauvegardees = sauvegarder_preferences(user["id"], data)
    return {"status": "ok", "user_id": user["id"], "preferences": sauvegardees}


@router.get("/favorites")
async def lire_favoris(user: dict = Depends(require_login)):
    """Récupère la liste des tickers favoris de l'utilisateur connecté."""
    favs = obtenir_favoris(user["id"])
    return {"status": "ok", "user_id": user["id"], "favorites": favs}


@router.post("/favorites")
async def modifier_favoris(request: Request, user: dict = Depends(require_login)):
    """Ajoute, supprime ou synchronise les favoris de l'utilisateur connecté.
    Accepte :
    - {"ticker": "AAPL", "action": "add" | "remove" | "toggle"}
    - ou {"favorites": ["AAPL", "MC.PA"]} (synchronisation complète)
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Corps JSON invalide")

    user_id = user["id"]
    if isinstance(data, dict) and "favorites" in data and isinstance(data["favorites"], list):
        favs = definir_favoris(user_id, data["favorites"])
        return {"status": "ok", "user_id": user_id, "favorites": favs}

    ticker = str(data.get("ticker", "")).strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker manquant ou invalide")

    action = str(data.get("action", "toggle")).lower()
    existants = obtenir_favoris(user_id)

    if action == "add":
        ajouter_favori(user_id, ticker)
    elif action == "remove":
        supprimer_favori(user_id, ticker)
    elif action == "toggle":
        if ticker in existants:
            supprimer_favori(user_id, ticker)
        else:
            ajouter_favori(user_id, ticker)
    else:
        raise HTTPException(status_code=400, detail=f"Action inconnue : {action}")

    derniers = obtenir_favoris(user_id)
    return {"status": "ok", "user_id": user_id, "favorites": derniers, "actif": ticker in derniers}
