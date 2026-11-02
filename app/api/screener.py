from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.templating import Jinja2Templates
import json
import asyncio
import os

from app.engine.fetcher import analyser_action_complete, analyser_tendances_macro, obtenir_taux_sans_risque

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

TICKERS_PAR_INDICE = {
    "CAC 40": ["AC.PA", "AI.PA", "AIR.PA", "MT.PA", "CS.PA", "BNP.PA", "EN.PA", "CAP.PA", "CA.PA", "ACA.PA", "BN.PA", "DSY.PA", "ENGI.PA", "EL.PA", "RMS.PA", "KER.PA", "OR.PA", "MC.PA", "ORA.PA", "PUB.PA", "RNO.PA", "SAF.PA", "SGO.PA", "SAN.PA", "SU.PA", "GLE.PA", "STLAM.PA", "TTE.PA", "URW.PA", "VIE.PA", "DG.PA"],
    "SP 500 - Mega Caps": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B", "UNH", "JNJ", "JPM", "V", "PG", "MA", "HD", "CVX", "ABBV", "LLY", "MRK", "PEP", "COST", "AVGO"],
    "SP 500 - Tech Titans": ["AMD", "INTC", "QCOM", "TXN", "ADBE", "CRM", "CSCO", "ACN", "ORCL", "IBM", "NOW", "INTU", "AMAT", "MU"],
    "SP 500 - Aristocrates": ["KO", "PEP", "JNJ", "PG", "MMM", "CAT", "CVX", "XOM", "WMT", "TGT", "MCD", "CL", "KMB"],
    "NASDAQ 100": ["AAPL", "ABNB", "ADBE", "ADI", "ADP", "AMAT", "AMD", "AMGN", "AMZN", "ASML", "AVGO", "CRWD", "CSCO", "DXCM", "GOOG", "GOOGL", "HON", "INTC", "ISRG", "META", "MRNA", "MSFT", "MU", "NFLX", "NVDA", "PANW", "PEP", "PYPL", "QCOM", "SBUX", "TSLA", "TXN"],
    "DAX 40": ["ADS.DE", "AIR.DE", "ALV.DE", "BAS.DE", "BAYN.DE", "BMW.DE", "DBK.DE", "DTE.DE", "IFX.DE", "MBG.DE", "MUV2.DE", "SAP.DE", "SIE.DE", "VOW3.DE"]
}

def analyser_recommandations_tous_indices(donnees_macro):
    tnx = donnees_macro.get("Taux 10 Ans", 0)
    return {
        "CAC 40": {"badge": "🟢 LUXE & INDUSTRIE", "conseil": "Diversification européenne solide."},
        "SP 500 - Mega Caps": {"badge": "🔥 LEADERS MONDIAUX", "conseil": "Les mastodontes qui dirigent l'économie."},
        "SP 500 - Tech Titans": {"badge": "⚡ OPPORTUNITÉ IA" if tnx < 4.0 else "⚠️ TAUX ÉLEVÉS", "conseil": "Haute volatilité, idéal pour jouer l'IA."},
        "SP 500 - Aristocrates": {"badge": "🛡️ RENDEMENT SÛR", "conseil": "Dividendes croissants face à l'inflation."},
        "NASDAQ 100": {"badge": "🚀 CROISSANCE", "conseil": "Moteur technologique pur."},
        "DAX 40": {"badge": "🏭 EXPORT", "conseil": "Cœur industriel de l'Europe."}
    }

@router.get("/", response_class=HTMLResponse)
async def terminal_unifie(request: Request, indice: str = "CAC 40"):
    donnees_macro = await asyncio.to_thread(analyser_tendances_macro)
    recoms = analyser_recommandations_tous_indices(donnees_macro)
    
    # Note le "T" majuscule ici si tu gardes le fichier sous le nom Terminal.html
    return templates.TemplateResponse(request, "Terminal.html", {
        "indice_actuel": indice,
        "recoms": recoms,
        "indices_dispos": list(TICKERS_PAR_INDICE.keys())
    })

@router.get("/stream")
async def flux_donnees_temps_reel(indice: str = "CAC 40"):
    donnees_macro = await asyncio.to_thread(analyser_tendances_macro)
    taux_du_jour = await asyncio.to_thread(obtenir_taux_sans_risque)
    tickers = TICKERS_PAR_INDICE.get(indice, TICKERS_PAR_INDICE["CAC 40"])

    async def generer_analyses():
        for ticker in tickers:
            resultat = await asyncio.to_thread(analyser_action_complete, ticker, [], taux_du_jour, donnees_macro)
            if resultat:
                yield f"data: {json.dumps(resultat)}\n\n"
            await asyncio.sleep(0.05)
        yield "event: close\ndata: end\n\n"

    return StreamingResponse(generer_analyses(), media_type="text/event-stream")