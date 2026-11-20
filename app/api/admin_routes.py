"""Espace administrateur : statistiques du cache, journal, utilisateurs, purge du cache.

Toutes les routes exigent le role admin via Depends(require_admin).
"""
import asyncio
import os
import sqlite3

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.auth_routes import require_admin
from app.engine.auth import lister_utilisateurs
from app.engine import journal
from app.engine.fetcher import vider_cache

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

racine = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db_cache_path = os.path.join(racine, "cache_bourse_v3.db")


def stats_cache() -> dict:
    """Statistiques du cache SQLite (nombre d'entrees, taille du fichier)."""
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
    return {"fichier": os.path.basename(db_cache_path), "taille_mo": round(taille, 2), "tables": tables}


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, user: dict = Depends(require_admin)):
    cache = await asyncio.to_thread(stats_cache)
    j = await asyncio.to_thread(journal.resume)
    users = await asyncio.to_thread(lister_utilisateurs)
    return templates.TemplateResponse(request, "admin.html", {
        "user": user, "cache": cache, "journal": j, "utilisateurs": users, "resultat": None})


@router.post("/admin/vider-cache", response_class=HTMLResponse)
async def admin_vider_cache(request: Request, user: dict = Depends(require_admin)):
    supprimes = await asyncio.to_thread(vider_cache)
    cache = await asyncio.to_thread(stats_cache)
    j = await asyncio.to_thread(journal.resume)
    users = await asyncio.to_thread(lister_utilisateurs)
    return templates.TemplateResponse(request, "admin.html", {
        "user": user, "cache": cache, "journal": j, "utilisateurs": users,
        "resultat": f"Cache vide : {supprimes} entrees supprimees."})
