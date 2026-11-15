"""Carte mentale économique & M&A : module ISOLÉ.

Il ne touche ni au scoring, ni à la base SQLite, ni aux routes existantes. Il expose :
  GET /mindmap                       la page (app/templates/mindmap.html, servie telle quelle)
  GET /api/mindmap-data              nœuds et liens (jeu de démonstration, répond tout de suite)
  GET /api/mindmap-data?live=true    idem, avec capitalisation / PER / performance depuis le 1er janvier
                                     rafraîchis par yfinance (cache 30 min ; repli sur la démo en cas d'échec)

Les RELATIONS (concurrence, rachats, chaîne de valeur) sont écrites à la main ci-dessous : à relire et à
compléter. Les valeurs chiffrées de démonstration (capitalisation, PER, performance) sont des ordres de
grandeur, remplacés par les valeurs en direct quand elles sont disponibles.
"""
import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter()
PAGE = Path(__file__).resolve().parent.parent / "templates" / "mindmap.html"      # app/templates/mindmap.html
SANS_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}
DELAI_LIVE = 40            # secondes d'attente maximum pour les données en direct
TTL_LIVE = 30 * 60         # durée de vie du cache des cours (secondes)

# --------------------------------------------------------------------------- #
# Données de démonstration
# --------------------------------------------------------------------------- #
SECTEURS = [
    ("tech", "Tech & IA"),
    ("semi", "Semi-conducteurs"),
    ("energie", "Énergie"),
    ("sante", "Santé"),
    ("finance", "Finance"),
]


def _e(id_, nom, ticker, secteur, role, cap, per=None, ytd=None, prive=False):
    """Société. cap : capitalisation en milliards de dollars (valorisation estimée si non cotée)."""
    return {"id": id_, "nom": nom, "ticker": ticker, "secteur": secteur, "role": role,
            "cap": cap, "per": per, "ytd": ytd, "prive": prive, "satellite": False}


ENTREPRISES = [
    # Tech & IA
    _e("msft", "Microsoft", "MSFT", "tech", "Cloud (Azure), logiciels, IA", 3800, 34, 12),
    _e("googl", "Alphabet", "GOOGL", "tech", "Recherche, cloud, IA (Gemini, puces TPU)", 3500, 27, 30),
    _e("amzn", "Amazon", "AMZN", "tech", "Commerce en ligne, cloud (AWS)", 2400, 33, 8),
    _e("meta", "Meta", "META", "tech", "Réseaux sociaux, publicité, IA", 1600, 26, -5),
    _e("aapl", "Apple", "AAPL", "tech", "Smartphones, services", 4000, 36, 9),
    _e("openai", "OpenAI", None, "tech", "Modèles d'IA (ChatGPT) ; non cotée, valorisation estimée", 500, None, None, True),
    _e("softbank", "SoftBank Group", "9984.T", "tech", "Holding d'investissement (Arm, OpenAI)", 130, None, 25),
    # Semi-conducteurs
    _e("nvda", "NVIDIA", "NVDA", "semi", "GPU et plateformes d'IA (CUDA)", 4500, 45, 35),
    _e("amd", "AMD", "AMD", "semi", "Processeurs, GPU et accélérateurs d'IA", 350, 80, 50),
    _e("intc", "Intel", "INTC", "semi", "Processeurs x86 et fonderie", 180, None, 60),
    _e("arm", "Arm", "ARM", "semi", "Architecture de processeurs (licences)", 150, 90, -8),
    _e("tsm", "TSMC", "TSM", "semi", "Fonderie de puces avancées", 1500, 28, 40),
    _e("asml", "ASML", "ASML", "semi", "Lithographie EUV, équipements", 400, 32, 18),
    _e("avgo", "Broadcom", "AVGO", "semi", "Puces réseau, ASIC d'IA, logiciels", 1600, 60, 45),
    _e("qcom", "Qualcomm", "QCOM", "semi", "Puces mobiles et connectivité", 170, 15, -12),
    _e("mu", "Micron", "MU", "semi", "Mémoire DRAM / HBM et stockage", 250, 25, 90),
    # Énergie
    _e("xom", "ExxonMobil", "XOM", "energie", "Pétrole et gaz intégré", 480, 15, 4),
    _e("cvx", "Chevron", "CVX", "energie", "Pétrole et gaz intégré", 300, 18, -3),
    _e("cop", "ConocoPhillips", "COP", "energie", "Exploration et production", 120, 12, -9),
    _e("shel", "Shell", "SHEL", "energie", "Pétrole, gaz, GNL", 210, 14, 6),
    _e("bp", "BP", "BP", "energie", "Pétrole, gaz, énergies bas carbone", 90, 10, -1),
    _e("tte", "TotalEnergies", "TTE.PA", "energie", "Pétrole, gaz, électricité", 140, 9, 3),
    # Santé
    _e("lly", "Eli Lilly", "LLY", "sante", "Obésité / diabète (GLP-1), oncologie", 800, 45, 25),
    _e("nvo", "Novo Nordisk", "NVO", "sante", "Diabète, obésité (sémaglutide)", 250, 18, -35),
    _e("pfe", "Pfizer", "PFE", "sante", "Vaccins, oncologie", 150, 12, -6),
    _e("mrk", "Merck", "MRK", "sante", "Oncologie (Keytruda), vaccins", 220, 14, -4),
    _e("abbv", "AbbVie", "ABBV", "sante", "Immunologie (Humira, Skyrizi)", 330, 60, 8),
    # Finance
    _e("jpm", "JPMorgan Chase", "JPM", "finance", "Banque universelle", 750, 14, 15),
    _e("bac", "Bank of America", "BAC", "finance", "Banque de détail et d'investissement", 380, 13, 10),
    _e("gs", "Goldman Sachs", "GS", "finance", "Banque d'investissement", 250, 15, 35),
    _e("ms", "Morgan Stanley", "MS", "finance", "Banque d'investissement, gestion de fortune", 260, 16, 28),
    _e("ubs", "UBS", "UBS", "finance", "Gestion de fortune, banque d'investissement", 120, 17, 5),
]

# Sociétés « satellites » : rachetées, filiales ou cibles d'offres. Sans capitalisation, elles n'apparaissent
# que reliées à un acquéreur.
SATELLITES = {
    "mellanox": "Mellanox", "runai": "Run:ai", "xilinx": "Xilinx", "zt": "ZT Systems", "ati": "ATI Technologies",
    "pensando": "Pensando", "silo": "Silo AI", "mobileye": "Mobileye", "altera": "Altera", "habana": "Habana Labs",
    "tower": "Tower Semiconductor", "nxp": "NXP Semiconductors", "vmware": "VMware", "ca": "CA Technologies",
    "symantec": "Symantec (entreprise)", "cymer": "Cymer", "hmi": "Hermes Microvision", "nuvia": "Nuvia",
    "alphawave": "Alphawave IP", "activision": "Activision Blizzard", "linkedin": "LinkedIn", "github": "GitHub",
    "nuance": "Nuance", "wiz": "Wiz", "mandiant": "Mandiant", "youtube": "YouTube", "motorola": "Motorola Mobility",
    "wholefoods": "Whole Foods", "mgm": "MGM", "irobot": "iRobot", "twitch": "Twitch", "instagram": "Instagram",
    "whatsapp": "WhatsApp", "oculus": "Oculus", "scaleai": "Scale AI", "beats": "Beats", "io": "io (Jony Ive)",
    "pioneer": "Pioneer Natural Resources", "xto": "XTO Energy", "hess": "Hess", "noble": "Noble Energy",
    "marathon": "Marathon Oil", "concho": "Concho Resources", "bg": "BG Group", "bhp": "BHP (actifs pétroliers US)",
    "maersk": "Maersk Oil", "seagen": "Seagen", "allergan": "Allergan", "prometheus": "Prometheus Biosciences",
    "loxo": "Loxo Oncology", "bearstearns": "Bear Stearns", "wamu": "Washington Mutual", "merrill": "Merrill Lynch",
    "countrywide": "Countrywide", "etrade": "E*Trade", "eaton": "Eaton Vance", "creditsuisse": "Credit Suisse",
}

# Concurrence directe : (société A, société B, intensité de 1 à 5, note). Lien symétrique.
CONCURRENCE = [
    ("nvda", "amd", 5, "GPU pour centres de données, jeu vidéo, IA"),
    ("nvda", "intc", 2, "Accélérateurs d'IA et GPU ; partenariat annoncé en septembre 2025"),
    ("nvda", "avgo", 3, "Accélérateurs sur mesure (ASIC) contre GPU"),
    ("nvda", "googl", 3, "Puces TPU de Google contre GPU NVIDIA"),
    ("amd", "intc", 5, "Processeurs x86 : PC et serveurs"),
    ("intc", "tsm", 3, "Intel Foundry contre TSMC"),
    ("arm", "intc", 3, "Architecture Arm contre x86"),
    ("qcom", "arm", 2, "Litige sur les licences d'architecture (depuis 2022)"),
    ("qcom", "aapl", 2, "Apple remplace progressivement les modems Qualcomm"),
    ("msft", "googl", 4, "Cloud, IA, bureautique"),
    ("msft", "amzn", 4, "Cloud : Azure contre AWS"),
    ("googl", "amzn", 3, "Cloud et publicité"),
    ("googl", "meta", 4, "Publicité en ligne"),
    ("msft", "openai", 2, "Partenaires, mais Copilot concurrence ChatGPT"),
    ("openai", "googl", 5, "ChatGPT contre Gemini"),
    ("openai", "meta", 3, "Modèles d'IA et assistants"),
    ("aapl", "googl", 3, "Systèmes mobiles et services"),
    ("aapl", "msft", 2, "Ordinateurs, services, IA"),
    ("xom", "cvx", 5, "Majors pétrolières américaines"),
    ("xom", "shel", 4, "Majors intégrées"),
    ("xom", "tte", 4, "Majors intégrées"),
    ("cvx", "shel", 3, "Majors intégrées"),
    ("shel", "bp", 5, "Majors britanniques"),
    ("bp", "tte", 4, "Majors européennes"),
    ("cvx", "cop", 4, "Production pétrolière américaine"),
    ("xom", "cop", 3, "Production pétrolière américaine"),
    ("lly", "nvo", 5, "Traitements GLP-1 de l'obésité et du diabète"),
    ("pfe", "mrk", 3, "Grands laboratoires généralistes"),
    ("mrk", "abbv", 3, "Oncologie et immunologie"),
    ("abbv", "pfe", 3, "Immunologie et oncologie"),
    ("jpm", "bac", 4, "Banques de détail américaines"),
    ("jpm", "gs", 3, "Banque d'investissement"),
    ("gs", "ms", 5, "Banque d'investissement"),
    ("bac", "ms", 3, "Gestion de fortune"),
    ("ubs", "gs", 3, "Banque d'investissement et gestion de fortune"),
    ("ubs", "ms", 3, "Gestion de fortune"),
    ("jpm", "ms", 3, "Banque d'investissement"),
]

# Rachats et participations : (acquéreur, cible, montant en Md$ ou None, année d'annonce, statut, note).
# statut : "finalisé", "annulé", "participation" ou "annoncé" (finalisation à vérifier).
MA = [
    ("nvda", "mellanox", 6.9, 2019, "finalisé", "Finalisé en avril 2020"),
    ("nvda", "runai", 0.7, 2024, "finalisé", "Orchestration de GPU"),
    ("nvda", "arm", 40, 2020, "annulé", "Abandonné en février 2022 (opposition des régulateurs)"),
    ("nvda", "intc", 5, 2025, "participation", "Investissement de 5 Md$ et partenariat sur les puces (annoncé en septembre 2025)"),
    ("nvda", "openai", 100, 2025, "participation", "Lettre d'intention de septembre 2025 : jusqu'à 100 Md$ investis progressivement ; conditions à vérifier"),
    ("amd", "xilinx", 35, 2020, "finalisé", "Échange d'actions, finalisé en février 2022"),
    ("amd", "zt", 4.9, 2024, "finalisé", "Finalisé en mars 2025 ; l'activité de fabrication a ensuite été cédée"),
    ("amd", "ati", 5.4, 2006, "finalisé", "Origine des GPU Radeon d'AMD"),
    ("amd", "pensando", 1.9, 2022, "finalisé", "Réseau pour centres de données"),
    ("amd", "silo", 0.7, 2024, "finalisé", "Laboratoire d'IA finlandais"),
    ("intc", "mobileye", 15.3, 2017, "finalisé", "Introduite en bourse en 2022 ; Intel reste actionnaire majoritaire"),
    ("intc", "altera", 16.7, 2015, "finalisé", "51 % cédés à Silver Lake en 2025"),
    ("intc", "habana", 2, 2019, "finalisé", "Accélérateurs d'IA Gaudi"),
    ("intc", "tower", 5.4, 2022, "annulé", "Abandonné en août 2023 (accord réglementaire non obtenu)"),
    ("softbank", "arm", 32, 2016, "finalisé", "Arm est coté depuis septembre 2023 ; SoftBank reste actionnaire majoritaire"),
    ("softbank", "openai", None, 2025, "participation", "Investisseur majeur et partenaire du projet Stargate ; montants à vérifier"),
    ("qcom", "nuvia", 1.4, 2021, "finalisé", "Cœurs de processeurs Oryon"),
    ("qcom", "alphawave", 2.4, 2025, "annoncé", "Connectivité pour centres de données ; finalisation à vérifier"),
    ("qcom", "nxp", 47, 2016, "annulé", "Abandonné en juillet 2018 (approbation chinoise non obtenue)"),
    ("avgo", "vmware", 61, 2022, "finalisé", "Finalisé en novembre 2023"),
    ("avgo", "ca", 18.9, 2018, "finalisé", "Logiciels d'infrastructure"),
    ("avgo", "symantec", 10.7, 2019, "finalisé", "Activité sécurité pour entreprises"),
    ("avgo", "qcom", 117, 2017, "annulé", "Offre hostile (≈130 Md$ dette comprise), bloquée par décret américain en mars 2018"),
    ("asml", "cymer", 2.5, 2012, "finalisé", "Sources de lumière pour lithographie"),
    ("asml", "hmi", 3.1, 2016, "finalisé", "Inspection par faisceau d'électrons (Taïwan)"),
    ("msft", "activision", 68.7, 2022, "finalisé", "Finalisé en octobre 2023"),
    ("msft", "linkedin", 26.2, 2016, "finalisé", "Réseau professionnel"),
    ("msft", "github", 7.5, 2018, "finalisé", "Plateforme de code"),
    ("msft", "nuance", 19.7, 2021, "finalisé", "Reconnaissance vocale, santé"),
    ("msft", "openai", 13, 2023, "participation", "≈13 Md$ investis depuis 2019 ; environ 27 % du capital après la recapitalisation d'octobre 2025"),
    ("googl", "youtube", 1.65, 2006, "finalisé", "Vidéo en ligne"),
    ("googl", "motorola", 12.5, 2011, "finalisé", "Cédée à Lenovo en 2014"),
    ("googl", "mandiant", 5.4, 2022, "finalisé", "Cybersécurité"),
    ("googl", "wiz", 32, 2025, "annoncé", "Sécurité du cloud ; finalisation à vérifier"),
    ("amzn", "wholefoods", 13.7, 2017, "finalisé", "Distribution alimentaire"),
    ("amzn", "mgm", 8.5, 2021, "finalisé", "Studio de cinéma"),
    ("amzn", "twitch", 1, 2014, "finalisé", "Vidéo en direct"),
    ("amzn", "irobot", 1.7, 2022, "annulé", "Abandonné en janvier 2024 (opposition de la Commission européenne)"),
    ("meta", "instagram", 1, 2012, "finalisé", "Réseau social de photos"),
    ("meta", "whatsapp", 19, 2014, "finalisé", "Messagerie"),
    ("meta", "oculus", 2, 2014, "finalisé", "Réalité virtuelle"),
    ("meta", "scaleai", 14.3, 2025, "participation", "49 % du capital (données pour l'IA)"),
    ("aapl", "beats", 3, 2014, "finalisé", "Audio et streaming"),
    ("aapl", "intc", 1, 2019, "finalisé", "Division modems 5G pour smartphones d'Intel"),
    ("openai", "io", 6.5, 2025, "finalisé", "Start-up de design de Jony Ive, rachetée en actions"),
    ("xom", "pioneer", 59.5, 2023, "finalisé", "Finalisé en mai 2024"),
    ("xom", "xto", 41, 2009, "finalisé", "Gaz de schiste"),
    ("cvx", "hess", 53, 2023, "finalisé", "Finalisé en juillet 2025 après un arbitrage"),
    ("cvx", "noble", 13, 2020, "finalisé", "Dette comprise"),
    ("cop", "marathon", 22.5, 2024, "finalisé", "Finalisé en novembre 2024"),
    ("cop", "concho", 9.7, 2020, "finalisé", "Échange d'actions"),
    ("shel", "bg", 70, 2015, "finalisé", "Gaz naturel liquéfié (≈47 Md£), finalisé en 2016"),
    ("bp", "bhp", 10.5, 2018, "finalisé", "Actifs de schiste américains de BHP"),
    ("tte", "maersk", 7.5, 2017, "finalisé", "Exploration en mer du Nord"),
    ("pfe", "seagen", 43, 2023, "finalisé", "Finalisé en décembre 2023"),
    ("abbv", "allergan", 63, 2019, "finalisé", "Finalisé en mai 2020"),
    ("mrk", "prometheus", 10.8, 2023, "finalisé", "Maladies auto-immunes"),
    ("lly", "loxo", 8, 2019, "finalisé", "Oncologie"),
    ("jpm", "bearstearns", 1.2, 2008, "finalisé", "Avec le soutien de la Réserve fédérale"),
    ("jpm", "wamu", 1.9, 2008, "finalisé", "Actifs bancaires repris via la FDIC"),
    ("bac", "merrill", 50, 2008, "finalisé", "Crise financière de 2008"),
    ("bac", "countrywide", 4, 2008, "finalisé", "Crédit immobilier"),
    ("ms", "etrade", 13, 2020, "finalisé", "Courtage en ligne"),
    ("ms", "eaton", 7, 2020, "finalisé", "Gestion d'actifs"),
    ("ubs", "creditsuisse", 3.2, 2023, "finalisé", "Rachat organisé par les autorités suisses (≈3 Md CHF)"),
]

# Chaîne de valeur : (fournisseur, client, note). Orienté du fournisseur vers le client.
SUPPLY = [
    ("tsm", "nvda", "Fabrication des GPU"),
    ("tsm", "amd", "Fabrication des processeurs et GPU"),
    ("tsm", "aapl", "Fabrication des puces Apple"),
    ("tsm", "avgo", "Fabrication des puces réseau et ASIC"),
    ("tsm", "qcom", "Fabrication des puces mobiles"),
    ("tsm", "intc", "Une partie des puces Intel est fabriquée chez TSMC"),
    ("asml", "tsm", "Machines de lithographie EUV"),
    ("asml", "intc", "Machines de lithographie EUV et High-NA"),
    ("arm", "aapl", "Licence d'architecture"),
    ("arm", "qcom", "Licence d'architecture"),
    ("arm", "nvda", "Licence : processeurs Grace"),
    ("arm", "amzn", "Licence : processeurs Graviton"),
    ("mu", "nvda", "Mémoire HBM pour les GPU"),
    ("nvda", "msft", "GPU pour le cloud Azure"),
    ("nvda", "meta", "GPU pour l'entraînement des modèles"),
    ("nvda", "openai", "GPU pour l'entraînement et l'inférence"),
    ("amd", "openai", "Accord de GPU d'octobre 2025, avec bons de souscription d'actions AMD"),
    ("avgo", "googl", "Conception des puces TPU"),
    ("avgo", "meta", "Puces d'IA sur mesure"),
    ("avgo", "openai", "Accélérateurs d'IA sur mesure (accord d'octobre 2025)"),
    ("msft", "openai", "Capacité de calcul sur Azure"),
    ("amzn", "openai", "Capacité de calcul sur AWS (accord de novembre 2025)"),
]

ORDRE_INDICES = ["NASDAQ 100", "Dow Jones", "CAC 40", "DAX 40", "Euro Stoxx 50", "FTSE 100", "Nikkei 225"]


def _indice_screener(ticker):
    """Premier indice du screener (app.api.screener.TICKERS_PAR_INDICE) qui contient ce ticker, sinon None."""
    if not ticker:
        return None
    try:
        from app.api.screener import TICKERS_PAR_INDICE
    except Exception:
        return None
    for nom in ORDRE_INDICES + list(TICKERS_PAR_INDICE):
        if ticker in TICKERS_PAR_INDICE.get(nom, ()):
            return nom
    return None


def construire():
    """Structure complète renvoyée au navigateur. Les liens vers une société inconnue sont ignorés."""
    ids = {e["id"] for e in ENTREPRISES} | set(SATELLITES)
    noeuds = []
    for e in ENTREPRISES:
        n = dict(e)
        n["indice"] = _indice_screener(e["ticker"])
        n["live"] = []                              # champs remplacés par des valeurs en direct
        noeuds.append(n)
    for id_, nom in SATELLITES.items():
        noeuds.append({"id": id_, "nom": nom, "ticker": None, "secteur": None, "role": "", "cap": None,
                       "per": None, "ytd": None, "prive": False, "satellite": True, "indice": None, "live": []})
    liens = []
    for a, b, intensite, note in CONCURRENCE:
        liens.append({"type": "concurrence", "source": a, "cible": b, "intensite": intensite, "note": note})
    for a, b, montant, annee, statut, note in MA:
        liens.append({"type": "ma", "source": a, "cible": b, "montant": montant, "annee": annee,
                      "statut": statut, "note": note})
    for a, b, note in SUPPLY:
        liens.append({"type": "supply", "source": a, "cible": b, "note": note})
    liens = [l for l in liens if l["source"] in ids and l["cible"] in ids]
    for i, l in enumerate(liens):
        l["id"] = f"e{i}"
    return {"meta": {"live": False, "nb_live": 0, "maj": datetime.now().strftime("%d/%m/%Y"),
                     "avertissement": "Valeurs chiffrées de démonstration (ordres de grandeur)."},
            "secteurs": [{"id": i, "nom": n} for i, n in SECTEURS], "noeuds": noeuds, "liens": liens}


# --------------------------------------------------------------------------- #
# Données en direct (yfinance), mises en cache
# --------------------------------------------------------------------------- #
_VERROU = threading.Lock()
_CACHE = {"t": 0.0, "data": {}}
SOUS_UNITES = {"GBp", "GBX", "ILA", "ZAc"}          # cotations en sous-unité : capitalisation ignorée (échelle incertaine)


def _num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if x != x or x in (float("inf"), float("-inf")) else x


def _cours_un(ticker):
    """{cap (Md$), per, ytd (%)} pour un ticker, ou None si Yahoo ne répond pas."""
    import pandas as pd
    import yfinance as yf
    t = yf.Ticker(ticker)
    info = t.info or {}
    devise = info.get("currency") or "USD"
    cap = _num(info.get("marketCap"))
    if cap is not None and devise != "USD":
        fx = None
        if devise not in SOUS_UNITES:
            try:
                from app.engine.fetcher import taux_change          # réutilise le cache de taux de change du screener
                fx = taux_change(devise, "USD")
            except Exception:
                fx = None
        cap = cap * fx if fx else None
    cap = cap / 1e9 if cap else None
    per = _num(info.get("trailingPE"))
    per = per if per and per > 0 else None
    ytd = None
    h = t.history(period="1y")["Close"].dropna()
    if len(h) > 30:
        annees = pd.DatetimeIndex(h.index).year
        avant = h[annees < annees[-1]]                               # dernière clôture de l'année précédente
        if len(avant) and avant.iloc[-1] > 0:
            ytd = float((h.iloc[-1] / avant.iloc[-1] - 1) * 100)
    if cap is None and per is None and ytd is None:
        return None
    return {"cap": cap, "per": per, "ytd": ytd}


def _charger_live():
    with _VERROU:
        if _CACHE["data"] and time.time() - _CACHE["t"] < TTL_LIVE:
            return dict(_CACHE["data"])
    res = {}
    cibles = [(e["id"], e["ticker"]) for e in ENTREPRISES if e["ticker"] and not e["prive"]]
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_cours_un, tk): id_ for id_, tk in cibles}
        for f in as_completed(futs):
            try:
                r = f.result()
            except Exception:
                r = None
            if r:
                res[futs[f]] = r
    if res:
        with _VERROU:
            _CACHE["t"], _CACHE["data"] = time.time(), res
    return res


def _fusionner(base, cours):
    """Remplace cap / per / ytd par les valeurs en direct (per et ytd même s'ils sont None : un PER absent
    signifie des bénéfices négatifs, pas une donnée manquante). La capitalisation de démo est gardée si Yahoo n'en donne pas."""
    nb = 0
    for n in base["noeuds"]:
        c = cours.get(n["id"])
        if not c:
            continue
        nb += 1
        if c["cap"] is not None:
            n["cap"] = c["cap"]
            n["live"].append("cap")
        n["per"], n["ytd"] = c["per"], c["ytd"]
        n["live"] += ["per", "ytd"]
    base["meta"].update(live=nb > 0, nb_live=nb, maj=datetime.now().strftime("%d/%m/%Y %H:%M"))
    return base


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@router.get("/mindmap", response_class=HTMLResponse)
async def page_mindmap():
    if not PAGE.exists():
        return HTMLResponse("<p style='font-family:sans-serif;padding:1rem'>app/templates/mindmap.html est introuvable.</p>",
                            status_code=404)
    return FileResponse(PAGE, headers=SANS_CACHE)


@router.get("/api/mindmap-data")
async def donnees_mindmap(live: bool = False):
    base = construire()
    if live:
        try:
            cours = await asyncio.wait_for(asyncio.to_thread(_charger_live), DELAI_LIVE)
        except Exception as e:                      # délai dépassé, Yahoo indisponible... : on reste sur la démo
            print(f"mindmap live : {type(e).__name__} {e}")
            with _VERROU:
                cours = dict(_CACHE["data"])
        base = _fusionner(base, cours)
    return base
