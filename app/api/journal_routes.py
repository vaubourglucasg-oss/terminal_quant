"""Routes du journal des signaux (lecture seule). Aucune route n'écrit : l'écriture se fait uniquement quand un scan
standard se termine (voir screener.py). Module isolé, comme mindmap_routes.py.

  GET /api/journal/resume        état du journal : nombre de scans, dates, versions du calcul
  GET /api/journal/export.csv    tout le journal en CSV (?indice=NASDAQ 100&depuis=2026-11-01)

PROTECTION. Ces routes exigent soit le rôle admin (session), soit un JOURNAL_TOKEN valide (pour les appels API
externes). Le jeton est vérifié via l'en-tête X-Journal-Token ou le paramètre ?token=...
"""
import asyncio
import hmac
import os
import re

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.engine import journal
from app.api.auth_routes import get_current_user

router = APIRouter()
SANS_CACHE = {"Cache-Control": "no-store"}
RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


async def _autoriser(request: Request, jeton: str):
    """Autorise l'accès si l'utilisateur est admin OU si le JOURNAL_TOKEN correspond."""
    # Vérifier d'abord la session admin
    user = await get_current_user(request)
    if user and user.get("role") == "admin":
        return  # Admin connecté, accès autorisé

    # Sinon, vérifier le jeton API
    attendu = os.environ.get("JOURNAL_TOKEN", "")
    if attendu and hmac.compare_digest(str(jeton or ""), attendu):
        return  # Jeton valide

    # Si ni admin ni jeton valide
    if not attendu:
        # Pas de JOURNAL_TOKEN configuré : exiger au moins un admin
        if not user:
            raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")
    else:
        raise HTTPException(status_code=403, detail="Accès refusé")


@router.get("/api/journal/resume")
async def journal_resume(request: Request, token: str = "", x_journal_token: str = Header(default="")):
    await _autoriser(request, x_journal_token or token)
    return JSONResponse(await asyncio.to_thread(journal.resume), headers=SANS_CACHE)


@router.get("/api/journal/export.csv")
async def journal_export(request: Request, indice: str = "", depuis: str = "", token: str = "", x_journal_token: str = Header(default="")):
    await _autoriser(request, x_journal_token or token)
    if depuis and not RE_DATE.match(depuis):
        raise HTTPException(status_code=400, detail="Date attendue : AAAA-MM-JJ")
    texte = await asyncio.to_thread(journal.exporter_csv, indice, depuis)
    return Response(texte, media_type="text/csv; charset=utf-8",
                    headers={**SANS_CACHE, "Content-Disposition": 'attachment; filename="journal_signaux.csv"'})
