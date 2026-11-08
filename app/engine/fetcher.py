import os
import math
import json
import time
import sqlite3
import threading
import hashlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf

from app.engine import math_models as mm

racine = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db_cache_path = os.path.join(racine, "cache_bourse_v3.db")
VERSION_SCHEMA = 3          # à incrémenter quand la structure des lignes change : invalide le cache

# --------------------------------------------------------------------------- #
# Hypothèses de valorisation (à réviser régulièrement)
# --------------------------------------------------------------------------- #
PRIMES_RISQUE_PAYS = {      # prime ajoutée au coût des fonds propres ; défaut 2 % si pays inconnu
    "United States": 0.00, "Switzerland": 0.00, "Germany": 0.00,
    "France": 0.004, "United Kingdom": 0.005, "Japan": 0.005, "China": 0.012, "India": 0.021,
}
HYP_DEFAUT = {"erp": 0.055, "g_term": 0.025, "rf": None, "ecart_g": 0.03, "ecart_ke": 0.01}


def normaliser_hypotheses(brut=None):
    """Hypothèses saisies dans l'interface (en %), converties en fractions et bornées."""
    brut = brut if isinstance(brut, dict) else {}

    def pct(cle, lo, hi):
        v = _f(brut.get(cle))
        return HYP_DEFAUT[cle] if v is None else min(hi, max(lo, v / 100.0))
    rf = _f(brut.get("rf"))
    return {"erp": pct("erp", 0.02, 0.10), "g_term": pct("g_term", 0.0, 0.04),
            "rf": None if rf is None else min(0.15, max(0.0, rf / 100.0)),
            "ecart_g": pct("ecart_g", 0.005, 0.08), "ecart_ke": pct("ecart_ke", 0.002, 0.04)}


def cle_hypotheses(hyp):
    """Vide pour les hypothèses par défaut (les caches existants restent valides), sinon une empreinte courte."""
    arrondi = lambda h: {k: (None if v is None else round(v, 6)) for k, v in h.items()}
    if arrondi(hyp) == arrondi(normaliser_hypotheses(None)):
        return ""
    return "|" + hashlib.md5(json.dumps(arrondi(hyp), sort_keys=True).encode()).hexdigest()[:8]


# Taux sans risque par devise (fraction, ex. {"JPY": 0.012, "EUR": 0.028}). VIDE par défaut : tout est alors
# actualisé avec le 10 ans américain, ce qui pénalise les marchés à taux bas (Japon, Suisse, zone euro).
RF_LOCAL = {}

BENCHMARKS = {
    "SP 500": "^GSPC", "S&P 500": "^GSPC", "NASDAQ 100": "^NDX", "Dow Jones": "^DJI", "TSX 60": "^GSPTSE",
    "CAC 40": "^FCHI", "DAX 40": "^GDAXI", "Euro Stoxx 50": "^STOXX50E", "FTSE 100": "^FTSE",
    "Ibex 35": "^IBEX", "FTSE MIB": "FTSEMIB.MI", "AEX Pays-Bas": "^AEX", "BEL 20": "^BFX",
    "SMI Suisse": "^SSMI", "OMXS30": "^OMX", "Nikkei 225": "^N225", "Hang Seng": "^HSI",
    "CSI 300": "000300.SS", "ASX 200": "^AXJO", "Nifty 50": "^NSEI", "Bovespa": "^BVSP",
}
# Yahoo cote certaines places en sous-unité (pence...) alors que les états financiers sont en unité
DEVISES_SOUS_UNITE = {"GBp": ("GBP", 0.01), "GBX": ("GBP", 0.01), "ILA": ("ILS", 0.01), "ZAc": ("ZAR", 0.01)}

MACRO_MAP = {
    "Pétrole WTI": "CL=F", "Gaz Naturel": "NG=F", "Uranium": "URA", "Solaire": "TAN",
    "Or": "GC=F", "Argent": "SI=F", "Cuivre": "HG=F", "Acier": "SLX", "Aluminium": "JJU",
    "Blé": "KE=F", "Bois": "CUT", "Taux 10 Ans": "^TNX", "Index Dollar": "DX-Y.NYB",
    "Fret Maritime": "BDRY", "Aéro & Défense": "ITA", "Semi-conducteurs": "^SOX",
    "Construction": "ITB", "Biotech": "IBB", "Santé": "XLV", "Banque": "XLF", "Volatilité VIX": "^VIX",
}
LIENS_MACRO = [("Gold", "Or"), ("Uranium", "Uranium"), ("Oil", "Pétrole WTI"), ("Aerospace", "Aéro & Défense"),
               ("Semiconductor", "Semi-conducteurs"), ("Copper", "Cuivre"), ("Steel", "Acier"),
               ("Solar", "Solaire"), ("Biotechnology", "Biotech"), ("Banks", "Banque")]

# --------------------------------------------------------------------------- #
# Utilitaires
# --------------------------------------------------------------------------- #
_verrou = threading.Lock()
_ttl = {}
ETAT_ERREURS = {"n": 0, "derniere": ""}      # affiché dans l'interface quand Yahoo refuse ou limite les requêtes


def _avec_ttl(cle, ttl, fabrique):
    """Cache mémoire à durée de vie (évite 21 téléchargements macro à chaque page)."""
    now = time.time()
    with _verrou:
        v = _ttl.get(cle)
        if v and now - v[0] < ttl:
            return v[1]
    valeur = fabrique()
    with _verrou:
        _ttl[cle] = (now, valeur)
    return valeur


def _f(x):
    """float propre ou None (rejette NaN, inf, chaînes comme 'Infinity')."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else x


def json_safe(o):
    if isinstance(o, dict):
        return {k: json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [json_safe(v) for v in o]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return _f(o)
    return o


# --------------------------------------------------------------------------- #
# Cache SQLite (JSON au lieu de pickle : lisible, sûr, versionné)
# --------------------------------------------------------------------------- #
def init_cache_db():
    conn = sqlite3.connect(db_cache_path, timeout=30)
    conn.execute("CREATE TABLE IF NOT EXISTS cache_actions "
                 "(ticker TEXT, date TEXT, version INTEGER, data TEXT, PRIMARY KEY (ticker, date, version))")
    conn.execute("DELETE FROM cache_actions WHERE date <= date('now', '-7 days')")
    conn.commit()
    conn.close()


def charger_du_cache(ticker, date_str):
    try:
        conn = sqlite3.connect(db_cache_path, timeout=30)
        row = conn.execute("SELECT data FROM cache_actions WHERE ticker=? AND date=? AND version=?",
                           (ticker, date_str, VERSION_SCHEMA)).fetchone()
        conn.close()
        return json.loads(row[0]) if row else None
    except Exception:
        return None


def vider_cache():
    """Vide le cache des analyses et la mémoire à durée de vie (macro, taux, change). Retourne le nombre de lignes."""
    n = 0
    try:
        conn = sqlite3.connect(db_cache_path, timeout=30)
        n = conn.execute("DELETE FROM cache_actions").rowcount
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Cache non vidé : {e}")
    with _verrou:
        _ttl.clear()
    return n


def sauvegarder_dans_cache(ticker, date_str, data):
    try:
        conn = sqlite3.connect(db_cache_path, timeout=30)
        conn.execute("INSERT OR REPLACE INTO cache_actions VALUES (?, ?, ?, ?)",
                     (ticker, date_str, VERSION_SCHEMA, json.dumps(data)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Cache non écrit pour {ticker} : {e}")


init_cache_db()


# --------------------------------------------------------------------------- #
# Macro, taux, change, indice de référence
# --------------------------------------------------------------------------- #
def _macro_un(nom, symbole):
    """Niveau, variation 1 mois et z-score : rendement 21 j / (vol quotidienne 3 mois × √21).
    Le z-score rend comparables un pétrole volatil et un dollar calme ; l'ancien écart à la MM40 en %
    était comparé à des seuils (« VIX < 18 ») qui n'avaient rien à voir avec son unité."""
    vide = {"niveau": None, "var_1m": 0.0, "z": 0.0}
    try:
        c = yf.Ticker(symbole).history(period="6mo")["Close"].dropna()
        if len(c) < 30:
            return nom, vide
        sig = c.pct_change().dropna().iloc[-63:].std()
        ret = c.iloc[-1] / c.iloc[-22] - 1
        z = float(ret / (sig * math.sqrt(21))) if sig and sig > 0 else 0.0
        return nom, {"niveau": float(c.iloc[-1]), "var_1m": float(ret * 100), "z": max(-4.0, min(4.0, z))}
    except Exception:
        return nom, vide


def analyser_tendances_macro():
    def charger():
        res = {}
        with ThreadPoolExecutor(max_workers=10) as ex:
            for fut in as_completed([ex.submit(_macro_un, n, s) for n, s in MACRO_MAP.items()]):
                n, v = fut.result()
                res[n] = v
        return res
    return _avec_ttl("macro", 1800, charger)


def obtenir_taux_sans_risque():
    def charger():
        try:
            niveau = yf.Ticker("^TNX").history(period="5d")["Close"].dropna().iloc[-1]
            t = float(niveau) / 100.0
            return t / 10 if t > 0.25 else t         # ancien format Yahoo : taux × 10
        except Exception:
            return 0.042
    return _avec_ttl("rf", 1800, charger)


def taux_change(de, vers):
    if de == vers:
        return 1.0

    def charger():
        try:
            c = yf.Ticker(f"{de}{vers}=X").history(period="5d")["Close"].dropna()
            return float(c.iloc[-1]) if len(c) else None
        except Exception:
            return None
    return _avec_ttl(("fx", de, vers), 6 * 3600, charger)


def obtenir_benchmark(indice):
    symbole = BENCHMARKS.get(indice)
    if not symbole:
        return None

    def charger():
        try:
            c = yf.Ticker(symbole).history(period="2y")["Close"].dropna()
            return c if len(c) > 100 else None
        except Exception:
            return None
    return _avec_ttl(("bench", symbole), 3600, charger)


def etiquette_macro(industrie, macro):
    for motif, cle in LIENS_MACRO:
        if motif.lower() in (industrie or "").lower():
            z = (macro.get(cle) or {}).get("z", 0.0)
            return f"{cle} {'▲' if z >= 1 else ('▼' if z <= -1 else '▬')}"
    return None


# --------------------------------------------------------------------------- #
# Analyse d'une action : métriques BRUTES uniquement (le scoring relatif est fait ensuite, sur l'ensemble)
# --------------------------------------------------------------------------- #
def analyser_action_brute(ticker_symbol, secteurs_cibles, rf_us, donnees_macro=None, bench=None, hyp=None):
    today = datetime.today().strftime("%Y-%m-%d")
    hyp = hyp or normaliser_hypotheses(None)
    cle_cache = ticker_symbol + cle_hypotheses(hyp)      # des hypothèses différentes = des résultats différents
    cache = charger_du_cache(cle_cache, today)
    if cache is not None:
        if secteurs_cibles and cache.get("secteur") not in secteurs_cibles:
            return None
        return cache

    try:
        t = yf.Ticker(ticker_symbol)
        info = t.info or {}
        secteur = info.get("sector") or "N/A"
        if secteurs_cibles and secteur not in secteurs_cibles:
            return None
        est_fin = secteur == "Financial Services"
        alertes = []

        # ---- devises : cote (pence → livres), états financiers, conversion ----
        devise_brute = info.get("currency") or "USD"
        devise, f_prix = DEVISES_SOUS_UNITE.get(devise_brute, (devise_brute, 1.0))
        dev_fin = info.get("financialCurrency") or devise
        dev_fin = DEVISES_SOUS_UNITE.get(dev_fin, (dev_fin, 1.0))[0]
        fx = taux_change(dev_fin, devise)
        fx_ok = fx is not None
        k = fx if fx_ok else 1.0
        if not fx_ok:
            alertes.append(f"Taux de change {dev_fin}→{devise} indisponible : valorisation non calculée")
        elif dev_fin != devise:
            alertes.append(f"États financiers en {dev_fin}, cours en {devise} : convertis au taux du jour")

        def m(x):
            x = _f(x)
            return None if x is None else x * k

        # ---- cours et historique ----
        try:
            hist = t.history(period="2y")
            close = (hist["Close"] * f_prix).dropna()
        except Exception:
            close = None
        brut = _f(info.get("currentPrice")) or _f(info.get("regularMarketPrice"))
        prix = brut * f_prix if brut else (float(close.iloc[-1]) if close is not None and len(close) else None)
        if not prix or prix <= 0:
            return None
        rf = RF_LOCAL.get(devise, rf_us)
        mk = mm.metriques_marche(close, rf, bench)
        if mk["prix"] is None:
            alertes.append("Historique de cours insuffisant (< 60 séances)")

        # ---- données de base ----
        actions = _f(info.get("sharesOutstanding")) or _f(info.get("impliedSharesOutstanding"))
        cap = _f(info.get("marketCap"))
        if actions and (f_prix != 1.0 or not cap):
            cap = prix * actions
        cash, dette = m(info.get("totalCash")), m(info.get("totalDebt"))
        cash0, dette0 = cash or 0.0, dette or 0.0
        ebitda, ca = m(info.get("ebitda")), m(info.get("totalRevenue"))
        fcf_ttm, eps, bvps = m(info.get("freeCashflow")), m(info.get("trailingEps")), m(info.get("bookValue"))
        roe, roa = _f(info.get("returnOnEquity")), _f(info.get("returnOnAssets"))
        marge_op = _f(info.get("operatingMargins"))

        def etat(attr):
            try:
                return getattr(t, attr)
            except Exception:
                return pd.DataFrame()
        fin, bs, cf = etat("financials"), etat("balance_sheet"), etat("cashflow")

        ebit = m(mm.val(mm.ligne(fin, "EBIT", "Operating Income"), 0))
        if ebit is None and marge_op is not None and ca:
            ebit = marge_op * ca
        fonds_propres = m(mm.val(mm.ligne(bs, "Common Stock Equity", "Stockholders Equity"), 0))
        if fonds_propres is None and bvps and actions:
            fonds_propres = bvps * actions
        interets = mm.val(mm.ligne(fin, "Interest Expense", "Interest Expense Non Operating"), 0)
        interets = None if interets is None else abs(interets) * k
        taux_is = mm.taux_effectif(fin)

        # ---- solidité ----
        nd_ebitda = ((dette0 - cash0) / ebitda) if (ebitda and ebitda > 0 and not est_fin) else None
        de = (dette0 / fonds_propres * 100) if (fonds_propres and fonds_propres > 0) else None
        pio, pio_n = mm.calculer_piotroski(fin, bs, cf)
        altman, zone = None, None
        if not est_fin and secteur != "Real Estate":
            tl = m(mm.val(mm.ligne(bs, "Total Liabilities Net Minority Interest", "Total Liabilities"), 0))
            ta = m(mm.val(mm.ligne(bs, "Total Assets"), 0))
            ac, pc = m(mm.val(mm.ligne(bs, "Current Assets"), 0)), m(mm.val(mm.ligne(bs, "Current Liabilities"), 0))
            res_ = m(mm.val(mm.ligne(bs, "Retained Earnings"), 0))
            fr = (ac - pc) if ac is not None and pc is not None else None
            altman, zone = mm.calculer_altman(secteur, ta, tl, fr, res_, ebit, cap, fonds_propres, ca)

        # ---- croissance ----
        cagr_ca = mm.cagr_serie(mm.ligne(fin, "Total Revenue"))
        fcf_l = mm.ligne(cf, "Free Cash Flow")
        if not fcf_l:
            cfo_l, capex_l = mm.ligne(cf, "Operating Cash Flow"), mm.ligne(cf, "Capital Expenditure")
            fcf_l = [(a + b) if a is not None and b is not None else None for a, b in zip(cfo_l, capex_l)]
        cagr_fcf = mm.cagr_serie(fcf_l)
        fcf_hist = [m(x) for x in fcf_l[:3] if x is not None]
        fcf_base = float(np.mean(fcf_hist)) if len(fcf_hist) >= 2 else fcf_ttm    # FCF normalisé sur 3 ans

        # ---- coût du capital, rentabilité ----
        beta = mk["beta"] if mk["beta"] is not None else (_f(info.get("beta")) or 1.0)
        prime_pays = PRIMES_RISQUE_PAYS.get(info.get("country", "United States"), 0.02)
        ke = mm.calculer_cout_capitaux(rf, beta, prime_pays, hyp["erp"])
        kd = mm.calculer_cout_dette(rf, interets, dette0, nd_ebitda)
        wacc = mm.calculer_wacc(ke, kd, taux_is, cap, dette0) * 100 if cap else None
        roic = None if est_fin else mm.calculer_roic(ebit, taux_is, fonds_propres, dette0, cash0)
        spread = (roic - wacc) if (roic is not None and wacc is not None) else None

        # ---- multiples ----
        ev = (cap + dette0 - cash0) if (cap and not est_fin) else None
        per = _f(info.get("trailingPE"))
        per = per if per and per > 0 else None
        ev_ebitda = ev / ebitda if (ev and ev > 0 and ebitda and ebitda > 0) else None
        ebitda_yield = ebitda / ev * 100 if (ev and ev > 0 and ebitda is not None and not est_fin) else None
        fcf_yield = fcf_ttm / cap * 100 if (cap and fcf_ttm is not None and not est_fin and fx_ok) else None
        earn_yield = (eps / prix * 100) if (eps is not None and fx_ok) else (100 / per if per else None)
        div = _f(info.get("trailingAnnualDividendYield"))      # fraction stable (dividendYield a changé d'unité)
        div_yield = div * 100 if div is not None else None

        # ---- valeur intrinsèque ----
        g_term = min(hyp["g_term"], max(0.01, rf - 0.005))
        valo = {"bear": None, "base": None, "bull": None}
        g1 = part_vt = g_imp = None
        methode = None
        if fx_ok:
            if est_fin:
                valo = mm.valorisation_financiere(roe, bvps, ke, g_term, prix, hyp["ecart_ke"])
                methode = "P/B justifié"
            elif fcf_base and fcf_base > 0 and actions:
                r = mm.valorisation_dcf(fcf_base, actions, cagr_ca, cagr_fcf, ke, g_term, prix, hyp["ecart_g"], hyp["ecart_ke"])
                valo = {n: r[n] for n in ("bear", "base", "bull")}
                g1, part_vt, g_imp = r["g1"], r["part_vt"], r["g_implicite"]
                methode = "DCF"
            elif not est_fin:
                alertes.append("FCF négatif ou indisponible : pas de DCF")
        if valo["base"] is not None and not (0.05 <= valo["base"] / prix <= 20):
            alertes.append("Valorisation incohérente avec le cours (devise ou unités ?) : ignorée")
            valo, g1, part_vt, g_imp = {"bear": None, "base": None, "bull": None}, None, None, None
        graham = None if (est_fin or secteur == "Technology" or not fx_ok) else mm.valeur_graham(eps, bvps)
        if graham is not None and not (0.1 <= graham / prix <= 10):
            graham = None
        if part_vt is not None and part_vt > 0.75:
            alertes.append(f"Valeur terminale = {part_vt * 100:.0f} % du DCF : résultat très sensible aux hypothèses")
        if g_imp is not None and g1 is not None and g_imp > g1 + 0.05:
            alertes.append("Le cours intègre une croissance nettement supérieure à celle retenue")

        row = {
            "ticker": ticker_symbol, "nom": info.get("shortName") or ticker_symbol, "secteur": secteur,
            "industrie": info.get("industry") or "", "est_fin": est_fin, "devise": devise, "prix": prix,
            "resume": (info.get("longBusinessSummary") or "Aucune description.")[:700],
            "url": f"https://finance.yahoo.com/quote/{ticker_symbol}/profile", "maj": datetime.today().strftime("%d/%m/%Y"),
            # valorisation
            "per": per, "ev_ebitda": ev_ebitda, "ebitda_yield": ebitda_yield, "fcf_yield": fcf_yield,
            "earn_yield": earn_yield, "div_yield": div_yield,
            # rentabilité
            "roic": roic, "wacc": wacc, "spread": spread, "marge_op": marge_op * 100 if marge_op is not None else None,
            "roe": roe * 100 if roe is not None else None, "roa": roa * 100 if roa is not None else None, "ke": ke * 100,
            # solidité
            "nd_ebitda": nd_ebitda, "de": de, "altman": altman, "altman_zone": zone,
            "piotroski": pio if pio_n else None, "piotroski_n": pio_n,
            # croissance
            "cagr_ca": cagr_ca * 100 if cagr_ca is not None else None,
            "cagr_fcf": cagr_fcf * 100 if cagr_fcf is not None else None,
            # marché / risque
            "vol": mk["vol"], "mdd": mk["mdd"], "rdt_1a": mk["rdt_1a"], "sharpe": mk["sharpe"], "sortino": mk["sortino"],
            "beta": beta if (mk["beta"] is not None or info.get("beta")) else None,
            "beta_local": mk["beta"] is not None, "mom_12_1": mk["mom_12_1"],
            "dist_ma200": mk["dist_ma200"], "dist_52w": mk["dist_52w"], "rsi": mk["rsi"],
            # valeur intrinsèque
            "methode_valo": methode, "valo_bear": valo["bear"], "valo_base": valo["base"], "valo_bull": valo["bull"],
            "marge_secu": mm.marge_securite(valo["base"], prix),
            "g_retenue": g1 * 100 if g1 is not None else None,
            "g_implicite": g_imp * 100 if g_imp is not None else None,
            "part_vt": part_vt * 100 if part_vt is not None else None,
            "graham": graham, "pot_graham": ((graham / prix - 1) * 100) if graham else None,
            "macro": etiquette_macro(info.get("industry"), donnees_macro or {}), "alertes": alertes,
        }
        row = json_safe(row)
        sauvegarder_dans_cache(cle_cache, today, row)
        return row
    except Exception as e:
        print(f"Erreur sur {ticker_symbol} : {e}")
        # Au lieu d'utiliser ETAT_ERREURS ici, on renvoie un dictionnaire explicite
        return {"erreur_ticker": ticker_symbol, "message": f"{type(e).__name__}: {e}"[:160]}