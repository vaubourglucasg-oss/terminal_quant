import os
import math
import json
import time
import shutil
import random
import sqlite3
import threading
import hashlib
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf

from app.engine import math_models as mm

racine = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.environ.get("DATA_DIR", "").strip() or racine
EST_FUSE = DATA_DIR.startswith("/mnt/") or DATA_DIR.startswith("/gcs/")

# Sur Cloud Run + GCS FUSE, SQLite tourne sur /tmp (RAM) et sauvegarde un snapshot propre sur /mnt/data
PERSISTENT_DB_PATH = os.path.join(DATA_DIR, "cache_bourse_v3.db") if EST_FUSE else None
db_cache_path = "/tmp/cache_bourse_v3.db" if EST_FUSE else os.path.join(DATA_DIR, "cache_bourse_v3.db")
VERSION_SCHEMA = 3

# --------------------------------------------------------------------------- #
# Hypothèses de valorisation
# --------------------------------------------------------------------------- #
PRIMES_RISQUE_PAYS = {
    "United States": 0.00, "Switzerland": 0.00, "Germany": 0.00,
    "France": 0.004, "United Kingdom": 0.005, "Japan": 0.005, "China": 0.012, "India": 0.021,
}
HYP_DEFAUT = {"erp": 0.055, "g_term": 0.025, "rf": None, "ecart_g": 0.03, "ecart_ke": 0.01}


def normaliser_hypotheses(brut=None):
    brut = brut if isinstance(brut, dict) else {}

    def pct(cle, lo, hi):
        v = _f(brut.get(cle))
        return HYP_DEFAUT[cle] if v is None else min(hi, max(lo, v / 100.0))
    rf = _f(brut.get("rf"))
    return {"erp": pct("erp", 0.02, 0.10), "g_term": pct("g_term", 0.0, 0.04),
            "rf": None if rf is None else min(0.15, max(0.0, rf / 100.0)),
            "ecart_g": pct("ecart_g", 0.005, 0.08), "ecart_ke": pct("ecart_ke", 0.002, 0.04)}


def cle_hypotheses(hyp):
    arrondi = lambda h: {k: (None if v is None else round(v, 6)) for k, v in h.items()}
    if arrondi(hyp) == arrondi(normaliser_hypotheses(None)):
        return ""
    return "|" + hashlib.md5(json.dumps(arrondi(hyp), sort_keys=True).encode()).hexdigest()[:8]


RF_LOCAL = {
    "EUR": 0.028, "GBP": 0.043, "CHF": 0.005, "JPY": 0.010,
    "CAD": 0.032, "AUD": 0.043, "SEK": 0.022, "HKD": 0.038,
    "CNY": 0.021, "INR": 0.068, "BRL": 0.125, "ILS": 0.045, "ZAR": 0.105,
}

BENCHMARKS = {
    "SP 500": "^GSPC", "S&P 500": "^GSPC", "NASDAQ 100": "^NDX", "Dow Jones": "^DJI", "TSX 60": "^GSPTSE",
    "CAC 40": "^FCHI", "DAX 40": "^GDAXI", "Euro Stoxx 50": "^STOXX50E", "FTSE 100": "^FTSE",
    "Ibex 35": "^IBEX", "FTSE MIB": "FTSEMIB.MI", "AEX Pays-Bas": "^AEX", "BEL 20": "^BFX",
    "SMI Suisse": "^SSMI", "OMXS30": "^OMX", "Nikkei 225": "^N225", "Hang Seng": "^HSI",
    "CSI 300": "000300.SS", "ASX 200": "^AXJO", "Nifty 50": "^NSEI", "Bovespa": "^BVSP",
}
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
# Utilitaires & Synchronisation GCS
# --------------------------------------------------------------------------- #
_verrou = threading.Lock()
_verrou_sync = threading.Lock()
_dernier_export_ts = 0.0
_dernier_import_mtime = 0.0
_dernier_check_import_ts = 0.0
_ttl = {}
ETAT_ERREURS = {"n": 0, "derniere": ""}


def _enregistrer_erreur(msg: str):
    with _verrou:
        ETAT_ERREURS["n"] += 1
        ETAT_ERREURS["derniere"] = str(msg)[:160]


def _avec_ttl(cle, ttl, fabrique):
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


def _importer_depuis_gcs(forcer: bool = False):
    """Copie séquentiellement la base persistante (/mnt/data) vers /tmp au démarrage ou si mise à jour externe."""
    global _dernier_import_mtime, _dernier_check_import_ts
    if not PERSISTENT_DB_PATH:
        return
    now = time.time()
    if not forcer and (now - _dernier_check_import_ts) < 20.0:
        return
    _dernier_check_import_ts = now

    with _verrou_sync:
        try:
            if not os.path.exists(PERSISTENT_DB_PATH):
                return
            mtime = os.path.getmtime(PERSISTENT_DB_PATH)
            if not forcer and os.path.exists(db_cache_path) and mtime <= _dernier_import_mtime:
                return
            tmp_in = db_cache_path + ".incoming"
            shutil.copyfile(PERSISTENT_DB_PATH, tmp_in)
            conn_test = sqlite3.connect(tmp_in, timeout=10)
            ok = conn_test.execute("PRAGMA integrity_check").fetchone()[0]
            conn_test.close()
            if ok == "ok":
                os.replace(tmp_in, db_cache_path)
                _dernier_import_mtime = mtime
            elif os.path.exists(tmp_in):
                os.remove(tmp_in)
        except Exception as e:
            print(f"Info import cache persistant : {e}")


def _exporter_vers_gcs(forcer: bool = False):
    """Exporte un snapshot SQLite cohérent et séquentiel vers /mnt/data (max 1 fois toutes les 5s)."""
    global _dernier_export_ts, _dernier_import_mtime
    if not PERSISTENT_DB_PATH or not os.path.exists(db_cache_path):
        return
    with _verrou_sync:
        now = time.time()
        if not forcer and (now - _dernier_export_ts) < 5.0:
            return
        snap_local = db_cache_path + ".snap"
        try:
            os.makedirs(os.path.dirname(PERSISTENT_DB_PATH), exist_ok=True)
            if os.path.exists(snap_local):
                os.remove(snap_local)
            src = sqlite3.connect(db_cache_path, timeout=20)
            dst = sqlite3.connect(snap_local, timeout=20)
            src.backup(dst)
            dst.close()
            src.close()

            # Écriture séquentielle en un seul flux sur GCS FUSE (zéro fichier .db-journal, zéro offset aléatoire)
            tmp_gcs = PERSISTENT_DB_PATH + f".tmp_{os.getpid()}"
            shutil.copyfile(snap_local, tmp_gcs)
            os.replace(tmp_gcs, PERSISTENT_DB_PATH)
            _dernier_export_ts = time.time()
            _dernier_import_mtime = os.path.getmtime(PERSISTENT_DB_PATH)
        except Exception as e:
            print(f"Erreur export snapshot vers {PERSISTENT_DB_PATH} : {e}")
        finally:
            if os.path.exists(snap_local):
                try:
                    os.remove(snap_local)
                except Exception:
                    pass


# --------------------------------------------------------------------------- #
# Cache SQLite local rapide (/tmp) + persistance GCS
# --------------------------------------------------------------------------- #
def _conn_cache():
    dossier = os.path.dirname(db_cache_path)
    if dossier:
        os.makedirs(dossier, exist_ok=True)
    conn = sqlite3.connect(db_cache_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_cache_db():
    _importer_depuis_gcs(forcer=True)
    conn = _conn_cache()
    try:
        for table in ("cache_actions", "cache_actions_staging"):
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    ticker TEXT,
                    date TEXT,
                    version INTEGER,
                    data TEXT,
                    last_updated TEXT,
                    indice TEXT,
                    categorie TEXT,
                    PRIMARY KEY (ticker, date, version)
                )
            """)
            cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if "last_updated" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN last_updated TEXT")
            if "indice" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN indice TEXT")
            if "categorie" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN categorie TEXT")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache_meta (
                cle TEXT PRIMARY KEY,
                valeur TEXT,
                last_updated TEXT
            )
        """)
        conn.execute("DELETE FROM cache_actions WHERE date <= date('now', '-30 days')")
        conn.commit()
    finally:
        conn.close()


def lire_meta(cle: str, defaut=None):
    try:
        conn = _conn_cache()
        try:
            row = conn.execute("SELECT valeur FROM cache_meta WHERE cle = ?", (cle,)).fetchone()
            return json.loads(row["valeur"]) if row else defaut
        finally:
            conn.close()
    except Exception:
        return defaut


def ecrire_meta(cle: str, valeur):
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        conn = _conn_cache()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO cache_meta (cle, valeur, last_updated) VALUES (?, ?, ?)",
                (cle, json.dumps(json_safe(valeur)), now_iso)
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"Erreur écriture meta {cle} : {e}")


def charger_du_cache(ticker, date_str=None, max_age_heures: float = 4.0, autoriser_perime: bool = True):
    """Lit uniquement depuis la table principale cache_actions."""
    _importer_depuis_gcs(forcer=False)
    try:
        conn = _conn_cache()
        try:
            if autoriser_perime or not date_str:
                row = conn.execute(
                    "SELECT data, last_updated FROM cache_actions WHERE ticker=? AND version=? ORDER BY date DESC, last_updated DESC LIMIT 1",
                    (ticker, VERSION_SCHEMA)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT data, last_updated FROM cache_actions WHERE ticker=? AND date=? AND version=?",
                    (ticker, date_str, VERSION_SCHEMA)
                ).fetchone()
            if not row:
                return None
            if not autoriser_perime and max_age_heures and row["last_updated"]:
                try:
                    maj = datetime.fromisoformat(row["last_updated"].replace("Z", "+00:00"))
                    if (datetime.now(timezone.utc) - maj).total_seconds() > max_age_heures * 3600.0:
                        return None
                except Exception:
                    pass
            return json.loads(row["data"])
        finally:
            conn.close()
    except Exception:
        return None


def charger_lot_du_cache(tickers: list[str]) -> dict[str, dict]:
    """Charge en une seule requête SQLite la dernière version valide de chaque ticker."""
    _importer_depuis_gcs(forcer=False)
    clean = list({t.strip() for t in tickers if t})
    if not clean:
        return {}
    resultat = {}
    conn = _conn_cache()
    try:
        for i in range(0, len(clean), 250):
            lot = clean[i:i + 250]
            ph = ",".join("?" for _ in lot)
            rows = conn.execute(f"""
                SELECT ticker, data
                FROM cache_actions
                WHERE version = ? AND ticker IN ({ph})
                ORDER BY date ASC, last_updated ASC
            """, [VERSION_SCHEMA, *lot]).fetchall()
            for r in rows:
                try:
                    resultat[r["ticker"]] = json.loads(r["data"])
                except Exception:
                    pass
    finally:
        conn.close()
    return resultat


def sauvegarder_dans_cache(ticker, date_str, data, indice=None, categorie="action", table="cache_actions"):
    if table not in ("cache_actions", "cache_actions_staging"):
        table = "cache_actions"
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(data, dict):
        data["maj"] = datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")
        data["last_updated"] = now_iso
    try:
        conn = _conn_cache()
        try:
            conn.execute(f"""
                INSERT OR REPLACE INTO {table} (ticker, date, version, data, last_updated, indice, categorie)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (ticker, date_str, VERSION_SCHEMA, json.dumps(json_safe(data)), now_iso, indice, categorie))
            conn.commit()
        finally:
            conn.close()
        if table == "cache_actions":
            _exporter_vers_gcs(forcer=False)
    except Exception as e:
        print(f"Cache ({table}) non écrit pour {ticker} : {e}")


def vider_staging(indices_cibles: list[str] | None = None):
    conn = _conn_cache()
    try:
        if indices_cibles:
            ph = ",".join("?" for _ in indices_cibles)
            conn.execute(f"DELETE FROM cache_actions_staging WHERE indice IN ({ph})", indices_cibles)
        else:
            conn.execute("DELETE FROM cache_actions_staging")
        conn.commit()
    finally:
        conn.close()


def valider_staging_vers_cache(indices_cibles: list[str] | None = None) -> int:
    """Bascule atomiquement staging -> cache_actions puis persiste un snapshot unique sur GCS."""
    conn = _conn_cache()
    nb_bascules = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        if indices_cibles:
            ph = ",".join("?" for _ in indices_cibles)
            rows = conn.execute(
                f"SELECT ticker, date, version, data, last_updated, indice, categorie FROM cache_actions_staging WHERE indice IN ({ph})",
                indices_cibles
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT ticker, date, version, data, last_updated, indice, categorie FROM cache_actions_staging"
            ).fetchall()

        if not rows:
            conn.execute("ROLLBACK")
            return 0

        tickers_maj = list({r["ticker"] for r in rows})
        for i in range(0, len(tickers_maj), 200):
            lot = tickers_maj[i:i + 200]
            ph = ",".join("?" for _ in lot)
            conn.execute(f"DELETE FROM cache_actions WHERE ticker IN ({ph})", lot)

        conn.executemany("""
            INSERT OR REPLACE INTO cache_actions (ticker, date, version, data, last_updated, indice, categorie)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [(r["ticker"], r["date"], r["version"], r["data"], r["last_updated"], r["indice"], r["categorie"]) for r in rows])

        if indices_cibles:
            ph = ",".join("?" for _ in indices_cibles)
            conn.execute(f"DELETE FROM cache_actions_staging WHERE indice IN ({ph})", indices_cibles)
        else:
            conn.execute("DELETE FROM cache_actions_staging")

        conn.commit()
        nb_bascules = len(rows)
    except Exception as e:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        print(f"Erreur bascule atomique staging -> cache : {e}")
        return 0
    finally:
        conn.close()

    if nb_bascules > 0:
        _exporter_vers_gcs(forcer=True)
    return nb_bascules


def lister_entrees_cache(limite: int = 500) -> list[dict]:
    _importer_depuis_gcs(forcer=False)
    conn = _conn_cache()
    try:
        rows = conn.execute("""
            SELECT ticker, date, version, last_updated, indice, categorie, LENGTH(data) as taille_octets
            FROM cache_actions
            ORDER BY date DESC, last_updated DESC
            LIMIT ?
        """, (limite,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def supprimer_entree_cache(ticker: str, date_str: str = None) -> int:
    conn = _conn_cache()
    try:
        if date_str:
            cur = conn.execute("DELETE FROM cache_actions WHERE ticker = ? AND date = ?", (ticker, date_str))
        else:
            cur = conn.execute("DELETE FROM cache_actions WHERE ticker = ?", (ticker,))
        conn.commit()
        n = cur.rowcount
    finally:
        conn.close()
    if n > 0:
        _exporter_vers_gcs(forcer=True)
    return n


def supprimer_cache_indice(indice: str, tickers: list[str] = None) -> int:
    conn = _conn_cache()
    try:
        cur1 = conn.execute("DELETE FROM cache_actions WHERE indice = ?", (indice,))
        n = cur1.rowcount
        if tickers:
            clean_tickers = [t.strip().upper() for t in tickers if t]
            if clean_tickers:
                placeholders = ",".join("?" for _ in clean_tickers)
                cur2 = conn.execute(f"DELETE FROM cache_actions WHERE ticker IN ({placeholders})", clean_tickers)
                n += cur2.rowcount
        conn.commit()
    finally:
        conn.close()
    if n > 0:
        _exporter_vers_gcs(forcer=True)
    return n


def vider_cache():
    n = 0
    try:
        conn = _conn_cache()
        try:
            n = conn.execute("DELETE FROM cache_actions").rowcount
            conn.execute("DELETE FROM cache_actions_staging")
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"Cache non vidé : {e}")
    with _verrou:
        _ttl.clear()
    _exporter_vers_gcs(forcer=True)
    return n


init_cache_db()


# --------------------------------------------------------------------------- #
# Macro, taux, change, indice de référence
# --------------------------------------------------------------------------- #
def _macro_un(nom, symbole):
    vide = {"niveau": None, "var_1m": 0.0, "z": 0.0}
    try:
        c = yf.Ticker(symbole).history(period="6mo")["Close"].dropna()
        c = c[c > 0]
        if len(c) < 30:
            return nom, vide
        log_ret = np.log(c / c.shift(1)).dropna().iloc[-63:]
        sig = float(log_ret.std())
        mu = float(log_ret.mean())
        ret_arith = float(c.iloc[-1] / c.iloc[-22] - 1.0)
        ret_log_21 = math.log(float(c.iloc[-1]) / float(c.iloc[-22]))
        z = float((ret_log_21 - 21.0 * mu) / (sig * math.sqrt(21.0))) if sig > 0 else 0.0
        return nom, {"niveau": float(c.iloc[-1]), "var_1m": ret_arith * 100.0, "z": max(-4.0, min(4.0, z))}
    except Exception:
        return nom, vide


def analyser_tendances_macro(forcer_yahoo: bool = False):
    if not forcer_yahoo:
        en_cache = lire_meta("macro")
        if isinstance(en_cache, dict) and en_cache:
            return en_cache
        return {nom: {"niveau": None, "var_1m": 0.0, "z": 0.0} for nom in MACRO_MAP}

    res = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for fut in as_completed([ex.submit(_macro_un, n, s) for n, s in MACRO_MAP.items()]):
            n, v = fut.result()
            res[n] = v
    if res:
        ecrire_meta("macro", res)
    return res


def obtenir_taux_sans_risque(forcer_yahoo: bool = False):
    if not forcer_yahoo:
        val = lire_meta("rf_us")
        if val is not None:
            return float(val)
        return 0.042

    try:
        niveau = yf.Ticker("^TNX").history(period="5d")["Close"].dropna().iloc[-1]
        t = float(niveau) / 100.0
        t = t / 10 if t > 0.25 else t
        ecrire_meta("rf_us", t)
        return t
    except Exception:
        val = lire_meta("rf_us")
        return float(val) if val is not None else 0.042


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
# Analyse d'une action depuis Yahoo Finance (Scheduler / Admin uniquement)
# --------------------------------------------------------------------------- #
def analyser_action_brute(ticker_symbol, secteurs_cibles, rf_us, donnees_macro=None, bench=None, hyp=None,
                          indice=None, table_cible="cache_actions_staging"):
    today = datetime.today().strftime("%Y-%m-%d")
    hyp = hyp or normaliser_hypotheses(None)
    cle_cache = ticker_symbol + cle_hypotheses(hyp)

    try:
        t = None
        info = {}
        for tentative in range(3):
            try:
                t = yf.Ticker(ticker_symbol)
                info = t.info or {}
                if info and (info.get("shortName") or info.get("currentPrice") or info.get("regularMarketPrice")):
                    break
            except Exception as e:
                if tentative == 2:
                    _enregistrer_erreur(f"{ticker_symbol}: {type(e).__name__}")
                    return None
            time.sleep(0.5 * (tentative + 1) + random.uniform(0.1, 0.3))

        secteur = info.get("sector") or "N/A"
        if secteurs_cibles and secteur != "N/A" and secteur not in secteurs_cibles:
            return None
        est_fin = secteur == "Financial Services"
        alertes = []

        # ---- devises ----
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
            _enregistrer_erreur(f"{ticker_symbol}: cours indisponible (Yahoo)")
            return None

        if secteurs_cibles and secteur not in secteurs_cibles:
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
        if eps is None and actions and actions > 0:
            net_inc = m(info.get("netIncomeToCommon"))
            if net_inc is not None:
                eps = net_inc / actions
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
        fcf_base = float(np.mean(fcf_hist)) if len(fcf_hist) >= 2 else fcf_ttm

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
        div = _f(info.get("trailingAnnualDividendYield"))
        div_yield = div * 100 if div is not None else None

        # ---- valeur intrinsèque ----
        g_term = min(hyp["g_term"], max(0.01, rf - 0.005))
        valo = {"bear": None, "base": None, "bull": None}
        g1 = part_vt = g_imp = None
        methode = None
        if fx_ok:
            if est_fin:
                g_term_fin = min(g_term, max(0.0, ke - 0.03))
                valo = mm.valorisation_financiere(roe, bvps, ke, g_term_fin, prix, hyp["ecart_ke"])
                methode = "P/B justifié"
            elif fcf_base and fcf_base > 0 and actions:
                taux_dcf = (wacc / 100.0) if (wacc is not None and wacc > 0) else ke
                g_term_dcf = min(g_term, max(0.0, taux_dcf - 0.03))
                dette_nette_ps = (dette0 - cash0) / actions
                prix_ev = prix + dette_nette_ps
                prix_ref = prix_ev if prix_ev > 0 else max(prix * 0.1, 1e-6)
                r = mm.valorisation_dcf(fcf_base, actions, cagr_ca, cagr_fcf, taux_dcf, g_term_dcf, prix_ref, hyp["ecart_g"], hyp["ecart_ke"])
                for sc in ("bear", "base", "bull"):
                    ev_ps = _f(r.get(sc))
                    valo[sc] = max(0.0, ev_ps - dette_nette_ps) if ev_ps is not None else None
                g1, part_vt = r["g1"], r["part_vt"]
                g_imp = r["g_implicite"] if prix_ev > 0 else None
                methode = "DCF (FCFF/WACC)"
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
            "url": f"https://finance.yahoo.com/quote/{ticker_symbol}/profile",
            "maj": datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"),
            "indice": indice,
            "per": per, "ev_ebitda": ev_ebitda, "ebitda_yield": ebitda_yield, "fcf_yield": fcf_yield,
            "earn_yield": earn_yield, "div_yield": div_yield,
            "roic": roic, "wacc": wacc, "spread": spread, "marge_op": marge_op * 100 if marge_op is not None else None,
            "roe": roe * 100 if roe is not None else None, "roa": roa * 100 if roa is not None else None, "ke": ke * 100,
            "nd_ebitda": nd_ebitda, "de": de, "altman": altman, "altman_zone": zone,
            "piotroski": pio if pio_n else None, "piotroski_n": pio_n,
            "cagr_ca": cagr_ca * 100 if cagr_ca is not None else None,
            "cagr_fcf": cagr_fcf * 100 if cagr_fcf is not None else None,
            "vol": mk["vol"], "mdd": mk["mdd"], "rdt_1a": mk["rdt_1a"], "sharpe": mk["sharpe"], "sortino": mk["sortino"],
            "beta": beta if (mk["beta"] is not None or info.get("beta")) else None,
            "beta_local": mk["beta"] is not None, "mom_12_1": mk["mom_12_1"],
            "dist_ma200": mk["dist_ma200"], "dist_ma50": mk.get("dist_ma50"), "dist_52w": mk["dist_52w"], "rsi": mk["rsi"],
            "methode_valo": methode, "valo_bear": valo["bear"], "valo_base": valo["base"], "valo_bull": valo["bull"],
            "marge_secu": mm.marge_securite(valo["base"], prix),
            "g_retenue": g1 * 100 if g1 is not None else None,
            "g_implicite": g_imp * 100 if g_imp is not None else None,
            "part_vt": part_vt * 100 if part_vt is not None else None,
            "graham": graham, "pot_graham": ((graham / prix - 1) * 100) if graham else None,
            "macro": etiquette_macro(info.get("industry"), donnees_macro or {}), "alertes": alertes,
        }
        row = json_safe(row)
        sauvegarder_dans_cache(cle_cache, today, row, indice=indice, table=table_cible)
        return row
    except Exception as e:
        print(f"Erreur sur {ticker_symbol} : {e}")
        _enregistrer_erreur(f"{ticker_symbol}: {type(e).__name__} {e}")
        return None