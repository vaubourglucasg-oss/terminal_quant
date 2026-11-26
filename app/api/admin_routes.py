import asyncio
import hmac
import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.api.auth_routes import require_admin
from app.engine.auth import lister_utilisateurs
from app.engine import journal
from app.api.screener import REGIONS, obtenir_tickers_pour_indice, RE_TICKER
from app.engine.fetcher import (vider_cache, lister_entrees_cache,
                                supprimer_entree_cache, supprimer_cache_indice,
                                db_cache_path, analyser_action_brute,
                                analyser_tendances_macro, obtenir_taux_sans_risque,
                                normaliser_hypotheses)
from app.engine.scheduler import (lancer_cycle_asynchrone, lancer_indice_asynchrone,
                                  obtenir_etat_refresh, est_marche_ouvert_ou_recente_cloture,
                                  executer_cycle_intelligent,
                                  acquerir_verrou, liberer_verrou)
router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def stats_cache() -> dict:
    if not os.path.exists(db_cache_path):
        return {"fichier": db_cache_path, "taille_mo": 0, "tables": {}}
    taille = os.path.getsize(db_cache_path) / (1024 * 1024)
    tables = {}
    try:
        conn = sqlite3.connect(db_cache_path, timeout=5)
        for (nom,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            count = conn.execute(f"SELECT COUNT(*) FROM [{nom}]").fetchone()[0]
            tables[nom] = count
        conn.close()
    except Exception:
        pass
    return {"fichier": db_cache_path, "taille_mo": round(taille, 2), "tables": tables}


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, user: dict = Depends(require_admin)):
    cache = await asyncio.to_thread(stats_cache)
    j = await asyncio.to_thread(journal.resume)
    users = await asyncio.to_thread(lister_utilisateurs)
    entrees = await asyncio.to_thread(lister_entrees_cache, 200)
    etat_refresh = await asyncio.to_thread(obtenir_etat_refresh)
    return templates.TemplateResponse(request=request, name="admin.html", context={
        "user": user, "cache": cache, "journal": j, "utilisateurs": users,
        "entrees_cache": entrees, "regions": REGIONS, "etat_refresh": etat_refresh, "resultat": None})


@router.post("/admin/vider-cache", response_class=HTMLResponse)
async def admin_vider_cache(request: Request, user: dict = Depends(require_admin)):
    await asyncio.to_thread(vider_cache)
    cache = await asyncio.to_thread(stats_cache)
    j = await asyncio.to_thread(journal.resume)
    users = await asyncio.to_thread(lister_utilisateurs)
    entrees = await asyncio.to_thread(lister_entrees_cache, 200)
    etat_refresh = await asyncio.to_thread(obtenir_etat_refresh)
    return templates.TemplateResponse(request=request, name="admin.html", context={
        "user": user, "cache": cache, "journal": j, "utilisateurs": users,
        "entrees_cache": entrees, "regions": REGIONS, "etat_refresh": etat_refresh, "resultat": None})


@router.get("/api/admin/cache/entries")
async def api_admin_lister_cache(limite: int = 500, user: dict = Depends(require_admin)):
    entrees = await asyncio.to_thread(lister_entrees_cache, limite)
    stats = await asyncio.to_thread(stats_cache)
    return {"status": "ok", "total": len(entrees), "stats": stats, "entries": entrees}


@router.get("/api/admin/cache/refresh-status")
async def api_admin_refresh_status(user: dict = Depends(require_admin)):
    etat = await asyncio.to_thread(obtenir_etat_refresh)
    stats = await asyncio.to_thread(stats_cache)
    return {"status": "ok", "refresh": etat, "stats": stats}


@router.post("/api/admin/cache/refresh-index/{index_name}")
async def api_admin_refresh_index(index_name: str, user: dict = Depends(require_admin)):
    """Charge manuellement un indice depuis Yahoo Finance vers staging puis bascule atomiquement."""
    lance = lancer_indice_asynchrone(index_name)
    if not lance:
        return JSONResponse(
            status_code=409,
            content={"status": "busy_or_invalid", "message": "Un chargement est déjà en cours ou indice invalide."}
        )
    return JSONResponse(
        status_code=202,
        content={"status": "started", "message": f"Chargement de {index_name} lancé en arrière-plan."}
    )


@router.post("/api/admin/cache/refresh-all")
async def api_admin_refresh_all(user: dict = Depends(require_admin)):
    """Charge manuellement les 20 indices depuis Yahoo Finance vers staging puis bascule atomiquement."""
    lance = lancer_cycle_asynchrone(mode="Admin (Complet)")
    if not lance:
        return JSONResponse(
            status_code=409,
            content={"status": "busy", "message": "Un chargement complet ou scheduler est déjà en cours."}
        )
    return JSONResponse(
        status_code=202,
        content={"status": "started", "message": "Mise à jour complète lancée en arrière-plan."}
    )


@router.post("/api/admin/cache/refresh-ticker/{ticker}")
async def api_admin_refresh_ticker(ticker: str, user: dict = Depends(require_admin)):
    """Recharge manuellement un seul ticker depuis Yahoo Finance directement dans le cache actif."""
    tk = ticker.strip().upper()
    if not RE_TICKER.match(tk):
        raise HTTPException(status_code=400, detail="Ticker invalide")
    rf = await asyncio.to_thread(obtenir_taux_sans_risque, True)
    macro = await asyncio.to_thread(analyser_tendances_macro, False)
    row = await asyncio.to_thread(
        analyser_action_brute, tk, [], rf, macro, None, normaliser_hypotheses(None), None, "cache_actions"
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"Impossible de récupérer {tk} sur Yahoo Finance")
    return {"status": "ok", "ticker": tk, "nom": row.get("nom"), "prix": row.get("prix")}


@router.delete("/api/admin/cache/entry")
async def api_admin_supprimer_entree(ticker: str = Query(...), date: str = Query(None), user: dict = Depends(require_admin)):
    supprimes = await asyncio.to_thread(supprimer_entree_cache, ticker, date)
    return {"status": "ok", "deleted": supprimes, "ticker": ticker, "date": date}


@router.delete("/api/admin/cache/index/{index_name}")
async def api_admin_supprimer_index(index_name: str, user: dict = Depends(require_admin)):
    tickers = obtenir_tickers_pour_indice(index_name)
    supprimes = await asyncio.to_thread(supprimer_cache_indice, index_name, tickers)
    return {"status": "ok", "deleted": supprimes, "indice": index_name}


@router.delete("/api/admin/cache/all")
async def api_admin_vider_tout_cache(user: dict = Depends(require_admin)):
    supprimes = await asyncio.to_thread(vider_cache)
    return {"status": "ok", "deleted": supprimes}


@router.post("/api/cron/refresh")
async def api_cron_refresh(request: Request):
    """Point d'entrée sécurisé pour Google Cloud Scheduler : remplit les continents manquants puis rafraîchit le plus vieux."""
    secret_attendu = os.environ.get("CRON_SECRET", "").strip()
    secret_fourni = request.headers.get("X-Cron-Secret", "").strip()

    if not secret_attendu or not hmac.compare_digest(secret_fourni, secret_attendu):
        raise HTTPException(status_code=403, detail="Secret cron invalide")

    _, msg_marche = est_marche_ouvert_ou_recente_cloture()
    if not acquerir_verrou("cycle_complet", duree_secondes=300):
        return JSONResponse(
            status_code=200,
            content={"status": "already_running", "message": "Une mise à jour est déjà en cours", "marche": msg_marche}
        )

    try:
        total_bascules = await asyncio.to_thread(executer_cycle_intelligent, "Cloud Scheduler")
    finally:
        liberer_verrou("cycle_complet")

    return JSONResponse(
        status_code=200,
        content={
            "status": "completed",
            "message": f"Cycle terminé ({total_bascules} titres basculés)",
            "marche": msg_marche
        }
    )