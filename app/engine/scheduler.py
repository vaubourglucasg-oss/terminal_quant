"""Planificateur intelligent d'arrière-plan (APScheduler) pour le Terminal Quantitatif.

Fonctionnalités :
1. Détection stricte des heures d'ouverture des marchés (Europe, USA, Asie) + buffer de clôture d'1 heure.
2. Rafraîchissement automatique toutes les 4 heures (uniquement si au moins un marché est actif).
3. Chargement décalé (Staggered) des grands indices toutes les 5 heures :
   - CAC 40 à T+0 min
   - S&P 500 à T+15 min
   - NASDAQ 100 à T+30 min
   - CSI 300 à T+45 min
   - Délai aléatoire (1 à 2s) entre les tickers pour éviter le code HTTP 429 de Yahoo Finance.
4. Verrou anti-doublon multi-workers (SQLite / fichier) pour éviter les exécutions concurrentes.
"""
import os
import time
import random
import logging
import sqlite3
import threading
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.engine.fetcher import (analyser_action_brute, analyser_tendances_macro,
                                obtenir_taux_sans_risque, obtenir_benchmark,
                                db_cache_path, normaliser_hypotheses)

logger = logging.getLogger("terminal_quant.scheduler")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [Scheduler] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

PARIS_TZ = ZoneInfo("Europe/Paris")

# Plages d'ouverture des marchés (heure de Paris) avec buffer de clôture de 1 heure
PLAGES_MARCHES = {
    "Europe (Euronext / CAC 40)": (dtime(9, 0), dtime(19, 0)),        # 09h00 - 18h00 (+1h = 19h00)
    "USA (NYSE / NASDAQ / S&P 500)": (dtime(15, 30), dtime(23, 30)),   # 15h30 - 22h30 (+1h = 23h30)
    "Asie (CSI 300)": (dtime(2, 30), dtime(9, 30)),                   # 02h30 - 08h30 (+1h = 09h30)
}

# Tickers par défaut des 4 grands indices pour le rafraîchissement d'arrière-plan
INDICES_STAGGERED = [
    {
        "nom": "CAC 40",
        "delai_min": 0,
        "tickers": [
            "AC.PA", "AI.PA", "AIR.PA", "MT.PA", "CS.PA", "BNP.PA", "EN.PA", "BVI.PA",
            "CAP.PA", "CA.PA", "ACA.PA", "BN.PA", "DSY.PA", "EL.PA", "ENGI.PA", "ERF.PA",
            "ENX.PA", "RMS.PA", "KER.PA", "OR.PA", "LR.PA", "MC.PA", "ML.PA", "ORA.PA",
            "RI.PA", "PUB.PA", "RNO.PA", "SAF.PA", "SGO.PA", "SAN.PA", "SU.PA", "GLE.PA",
            "STLAM.PA", "STMPA.PA", "HO.PA", "TTE.PA", "URW.PA", "VIE.PA", "DG.PA"
        ]
    },
    {
        "nom": "S&P 500",
        "delai_min": 15,
        "tickers": [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B", "UNH", "JNJ",
            "JPM", "V", "PG", "MA", "HD", "CVX", "ABBV", "LLY", "MRK", "PEP", "COST", "KO",
            "AVGO", "MCD", "WMT", "CRM", "CSCO", "BAC", "LIN", "AMD", "ADBE", "ORCL", "NFLX"
        ]
    },
    {
        "nom": "NASDAQ 100",
        "delai_min": 30,
        "tickers": [
            "AAPL", "ABNB", "ADBE", "ADI", "ADP", "AMAT", "AMD", "AMGN", "AMZN", "ASML",
            "AVGO", "BKNG", "CDNS", "COST", "CSCO", "GOOG", "GOOGL", "INTC", "INTU", "ISRG",
            "KLAC", "LIN", "LRCX", "META", "MRVL", "MSFT", "MU", "NFLX", "NVDA", "PANW",
            "PDD", "PEP", "PYPL", "QCOM", "REGN", "SBUX", "SNPS", "TMUS", "TSLA", "TXN"
        ]
    },
    {
        "nom": "CSI 300",
        "delai_min": 45,
        "tickers": [
            "600519.SS", "601398.SS", "601288.SS", "601857.SS", "601988.SS",
            "600036.SS", "601318.SS", "600900.SS", "601088.SS", "000858.SZ",
            "000333.SZ", "002594.SZ", "300750.SZ", "601899.SS", "600030.SS"
        ]
    }
]

_scheduler = None
_thread_staggered = None
_stop_event = threading.Event()


def est_marche_ouvert_ou_recente_cloture(dt: datetime | None = None) -> tuple[bool, str]:
    """Vérifie si au moins un des marchés principaux est ouvert ou vient de clôturer dans l'heure."""
    if dt is None:
        dt = datetime.now(PARIS_TZ)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=PARIS_TZ)
    else:
        dt = dt.astimezone(PARIS_TZ)

    # Marchés fermés le week-end (samedi=5, dimanche=6)
    if dt.weekday() >= 5:
        return False, "Week-end : tous les marchés sont fermés"

    t = dt.time()
    actifs = []
    for nom, (ouv, clot) in PLAGES_MARCHES.items():
        if ouv <= t <= clot:
            actifs.append(nom)

    if actifs:
        return True, f"Marchés actifs ({', '.join(actifs)}) à {t.strftime('%H:%M')} (Paris)"
    return False, f"Aucun marché actif à {t.strftime('%H:%M')} (Paris)"


def init_table_verrou():
    """Crée la table de verrous d'exécution dans SQLite pour éviter les doublons multi-workers."""
    try:
        conn = sqlite3.connect(db_cache_path, timeout=10)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduler_locks (
                job_id TEXT PRIMARY KEY,
                worker_pid INTEGER,
                expire_le REAL
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Erreur init table scheduler_locks : {e}")


def acquerir_verrou(job_id: str, duree_secondes: int = 1800) -> bool:
    """Acquiert un verrou d'exécution pour un job donné."""
    init_table_verrou()
    maintenant = time.time()
    expire = maintenant + duree_secondes
    pid = os.getpid()
    try:
        conn = sqlite3.connect(db_cache_path, timeout=5)
        # Supprime les verrous expirés
        conn.execute("DELETE FROM scheduler_locks WHERE expire_le < ?", (maintenant,))
        # Tente d'insérer le nouveau verrou
        try:
            conn.execute("INSERT INTO scheduler_locks (job_id, worker_pid, expire_le) VALUES (?, ?, ?)",
                         (job_id, pid, expire))
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            conn.close()
            return False
    except Exception as e:
        logger.warning(f"Erreur tentative acquisition verrou {job_id} : {e}")
        return False


def liberer_verrou(job_id: str):
    """Libère le verrou après terminaison du job."""
    try:
        conn = sqlite3.connect(db_cache_path, timeout=5)
        conn.execute("DELETE FROM scheduler_locks WHERE job_id = ? AND worker_pid = ?", (job_id, os.getpid()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Erreur libération verrou {job_id} : {e}")


def job_mise_a_jour_4h():
    """Tâche exécutée toutes les 4 heures : actualise le contexte macro si un marché est actif."""
    ouvert, msg = est_marche_ouvert_ou_recente_cloture()
    if not ouvert:
        logger.info(f"[Job 4h] Ignoré : {msg}.")
        return

    if not acquerir_verrou("job_4h", duree_secondes=7200):
        logger.info("[Job 4h] Verrou déjà détenu par un autre worker.")
        return

    try:
        logger.info(f"[Job 4h] Démarrage de l'actualisation globale ({msg}).")
        analyser_tendances_macro()
        obtenir_taux_sans_risque()
        logger.info("[Job 4h] Actualisation des indicateurs macro terminée avec succès.")
    except Exception as e:
        logger.error(f"[Job 4h] Erreur lors de l'actualisation : {e}")
    finally:
        liberer_verrou("job_4h")


def _executer_staggered_indices():
    """Cycle de chargement décalé (staggered) pour les 4 grands indices."""
    logger.info("[Staggered] Début de la séquence décalée des 4 grands indices.")
    rf = obtenir_taux_sans_risque()
    macro = analyser_tendances_macro()
    hyp_defaut = normaliser_hypotheses(None)

    for item in INDICES_STAGGERED:
        if _stop_event.is_set():
            logger.info("[Staggered] Annulation demandée.")
            break

        nom_indice = item["nom"]
        delai_min = item["delai_min"]
        tickers = item["tickers"]

        logger.info(f"[Staggered] Étape {nom_indice} (décalage théorique T+{delai_min} min).")
        ouvert, msg = est_marche_ouvert_ou_recente_cloture()
        if not ouvert:
            logger.info(f"[Staggered] {nom_indice} ignoré car les marchés sont fermés ({msg}).")
            continue

        bench = obtenir_benchmark(nom_indice)
        total = len(tickers)
        for i, tk in enumerate(tickers):
            if _stop_event.is_set():
                break
            try:
                # Analyse et sauvegarde dans le cache global avec tag de l'indice
                analyser_action_brute(tk, [], rf, macro, bench, hyp_defaut, indice=nom_indice)
            except Exception as e:
                logger.warning(f"[Staggered] Erreur ticker {tk} : {e}")

            # Délai aléatoire anti-rate-limit (1.0 à 2.0 s)
            pause = random.uniform(1.0, 2.0)
            time.sleep(pause)

        logger.info(f"[Staggered] Indice {nom_indice} ({total} titres traités) terminé.")

        # Pause avant de passer à l'indice suivant si ce n'est pas le dernier
        if item != INDICES_STAGGERED[-1] and not _stop_event.is_set():
            logger.info("[Staggered] Pause de 15 minutes avant le prochain indice...")
            # Attente par intervalles pour réactivité à l'arrêt
            for _ in range(15 * 6):
                if _stop_event.is_set():
                    break
                time.sleep(10)

    logger.info("[Staggered] Séquence complète terminée.")


def job_staggered_indices():
    """Tâche exécutée toutes les ~5 heures : lance la séquence décalée en arrière-plan."""
    ouvert, msg = est_marche_ouvert_ou_recente_cloture()
    if not ouvert:
        logger.info(f"[Job 5h] Ignoré : {msg}.")
        return

    if not acquerir_verrou("job_5h_staggered", duree_secondes=14400):
        logger.info("[Job 5h] Verrou déjà détenu par un autre worker.")
        return

    def runner():
        try:
            _executer_staggered_indices()
        finally:
            liberer_verrou("job_5h_staggered")

    thread = threading.Thread(target=runner, daemon=True, name="staggered-indices-worker")
    thread.start()


def demarrer_scheduler() -> BackgroundScheduler:
    """Démarre le scheduler d'arrière-plan."""
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    _stop_event.clear()
    _scheduler = BackgroundScheduler(timezone=PARIS_TZ)

    # 1. Mise à jour toutes les 4 heures
    _scheduler.add_job(
        job_mise_a_jour_4h,
        trigger=IntervalTrigger(hours=4, timezone=PARIS_TZ),
        id="job_mise_a_jour_4h",
        replace_existing=True,
        max_instances=1
    )

    # 2. Chargement décalé (Staggered) toutes les 5 heures
    _scheduler.add_job(
        job_staggered_indices,
        trigger=IntervalTrigger(hours=5, timezone=PARIS_TZ),
        id="job_staggered_indices",
        replace_existing=True,
        max_instances=1
    )

    _scheduler.start()
    logger.info("Planificateur APScheduler démarré avec succès (jobs : 4h global, 5h staggered).")
    return _scheduler


def arreter_scheduler():
    """Arrête proprement le scheduler et les workers en cours."""
    global _scheduler
    _stop_event.set()
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Planificateur APScheduler arrêté.")
