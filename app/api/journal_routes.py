"""Routes du journal des signaux (lecture seule). Aucune route n'écrit : l'écriture se fait uniquement quand un scan
standard se termine (voir screener.py). Module isolé, comme mindmap_routes.py.

  GET /api/journal/resume        état du journal : nombre de scans, dates, versions du calcul
  GET /api/journal/export.csv    tout le journal en CSV (?indice=NASDAQ 100&depuis=2026-11-01)

PROTECTION. Si la variable d'environnement JOURNAL_TOKEN est définie, le jeton est exigé (en-tête X-Journal-Token, ou
?token=... pour un téléchargement depuis le navigateur). Sans variable, les routes sont ouvertes : acceptable en local,
JAMAIS en ligne. Avant la mise en production, ces routes doivent passer derrière l'espace administrateur.
"""
import asyncio
import hmac
import os
import re

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse, Response

from app.engine import journal

router = APIRouter()
SANS_CACHE = {"Cache-Control": "no-store"}
RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _autoriser(jeton):
    attendu = os.environ.get("JOURNAL_TOKEN", "")
    if attendu and not hmac.compare_digest(str(jeton or ""), attendu):
        raise HTTPException(status_code=403, detail="Accès refusé")


@router.get("/api/journal/resume")
async def journal_resume(token: str = "", x_journal_token: str = Header(default="")):
    _autoriser(x_journal_token or token)
    return JSONResponse(await asyncio.to_thread(journal.resume), headers=SANS_CACHE)


@router.get("/api/journal/export.csv")
async def journal_export(indice: str = "", depuis: str = "", token: str = "", x_journal_token: str = Header(default="")):
    _autoriser(x_journal_token or token)
    if depuis and not RE_DATE.match(depuis):
        raise HTTPException(status_code=400, detail="Date attendue : AAAA-MM-JJ")
    texte = await asyncio.to_thread(journal.exporter_csv, indice, depuis)
    return Response(texte, media_type="text/csv; charset=utf-8",
                    headers={**SANS_CACHE, "Content-Disposition": 'attachment; filename="journal_signaux.csv"'})
