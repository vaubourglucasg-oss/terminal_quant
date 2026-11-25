import os
import time
import random
import logging
import sqlite3
import threading
from datetime import datetime, time as dtime, timezone
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.engine.fetcher import (analyser_action_brute, analyser_tendances_macro,
                                obtenir_taux_sans_risque, obtenir_benchmark,
                                db_cache_path, normaliser_hypotheses, _conn_cache,
                                charger_du_cache)
from app.api.screener import REGIONS, obtenir_tickers_pour_indice

logger = logging.getLogger("terminal_quant.scheduler")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [Scheduler] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

PARIS_TZ = ZoneInfo("Europe/Paris")

PLAGES_MARCHES = {
    "Europe (Euronext / CAC 40 / DAX / FTSE)": (dtime(9, 0), dtime(19, 0)),
    "USA (NYSE / NASDAQ / SP 500)": (dtime(15, 30), dtime(23, 30)),
    "Asie-Pacifique (CSI 300 / Nikkei / ASX)": (dtime(1, 0), dtime(9, 30)),
}

TOUS_LES_INDICES = [nom for groupe in REGIONS.values() for nom in groupe]
DELAI_ENTRE_INDICES_MIN = 0.25  # 15 secondes entre chaque indice

_scheduler = None
_stop_event = threading.Event()


def est_marche_ouvert_ou_recente_cloture(dt: datetime | None = None) -> tuple[bool, str]:
    if dt is None:
        dt = datetime.now(PARIS_TZ)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=PARIS_TZ)
    else:
        dt = dt.astimezone(PARIS_TZ)

    if dt.weekday() >= 5:
        return False, "Week-end : tous les marchés sont fermés"

    t = dt.time()
    actifs = [nom for nom, (ouv, clot) in PLAGES_MARCHES.items() if ouv <= t <= clot]
    if actifs:
        return True, f"Marchés actifs ({', '.join(actifs)}) à {t.strftime('%H:%M')} (Paris)"
    return False, f"Aucun marché mondial actif à {t.strftime('%H:%M')} (Paris)"


def init_table_verrou():
    try:
        conn = _conn_cache()
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


def acquerir_verrou(job_id: str, duree_secondes: int = 3600) -> bool:
    init_table_verrou()
    maintenant = time.time()
    expire = maintenant + duree_secondes
    pid = os.getpid()
    try:
        conn = _conn_cache()
        conn.execute("DELETE FROM scheduler_locks WHERE expire_le < ?", (maintenant,))
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
    try:
        conn = _conn_cache()
        conn.execute("DELETE FROM scheduler_locks WHERE job_id = ? AND worker_pid = ?", (job_id, os.getpid()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Erreur libération verrou {job_id} : {e}")


def _charger_un_indice(nom_indice: str, rf: float, macro: dict, hyp: dict, max_age_check: float = 3.5):
    bench = obtenir_benchmark(nom_indice)
    tickers = list(dict.fromkeys(obtenir_tickers_pour_indice(nom_indice)))
    today = datetime.today().strftime("%Y-%m-%d")

    a_traiter = [
        tk for tk in tickers
        if not (max_age_check and charger_du_cache(tk, today, max_age_heures=max_age_check) is not None)
    ]

    logger.info(f"[{nom_indice}] {len(tickers)} titres au total, {len(a_traiter)} à analyser/rafraîchir.")
    if not a_traiter:
        return

    def worker_action(tk):
        if _stop_event.is_set():
            return None
        try:
            res = analyser_action_brute(tk, [], rf, macro, bench, hyp, indice=nom_indice)
        except Exception as e:
            logger.warning(f"[{nom_indice}] Erreur {tk}: {e}")
            res = None
        time.sleep(random.uniform(0.8, 1.5))
        return res

    with ThreadPoolExecutor(max_workers=2) as executor:
        futurs = [executor.submit(worker_action, tk) for tk in a_traiter]
        for f in as_completed(futurs):
            if _stop_event.is_set():
                break
            try:
                f.result()
            except Exception:
                pass


def _executer_cycle_complet(max_age_check: float = 3.5):
    logger.info(f"[Scheduler] Démarrage du cycle intégral sur les {len(TOUS_LES_INDICES)} indices.")
    rf = obtenir_taux_sans_risque()
    macro = analyser_tendances_macro()
    hyp_defaut = normaliser_hypotheses(None)

    for i, nom_indice in enumerate(TOUS_LES_INDICES):
        if _stop_event.is_set():
            logger.info("[Scheduler] Arrêt prématuré du cycle complet.")
            break

        if i > 0:
            pause_sec = int(DELAI_ENTRE_INDICES_MIN * 60)
            for _ in range(max(1, pause_sec // 5)):
                if _stop_event.is_set():
                    return
                time.sleep(5)

        logger.info(f"[Scheduler] ({i+1}/{len(TOUS_LES_INDICES)}) Traitement de l'indice {nom_indice}...")
        try:
            _charger_un_indice(nom_indice, rf, macro, hyp_defaut, max_age_check=max_age_check)
        except Exception as e:
            logger.error(f"[Scheduler] Erreur lors du traitement de {nom_indice} : {e}")

    logger.info("[Scheduler] Cycle complet sur les 20 indices achevé avec succès.")


def lancer_cycle_asynchrone(max_age_check: float = 3.5) -> bool:
    """Lance le cycle complet dans un thread d'arrière-plan protégé par verrou."""
    if not acquerir_verrou("cycle_complet", duree_secondes=7200):
        logger.info("[Scheduler] Cycle déjà en cours sur un worker, appel ignoré.")
        return False

    def runner():
        try:
            _executer_cycle_complet(max_age_check=max_age_check)
        finally:
            liberer_verrou("cycle_complet")

    thread = threading.Thread(target=runner, daemon=True, name="cron-cycle-worker")
    thread.start()
    return True


def job_mise_a_jour_4h():
    ouvert, msg = est_marche_ouvert_ou_recente_cloture()
    if not ouvert:
        logger.info(f"[Job 4h] Ignoré : {msg}.")
        return

    if not acquerir_verrou("job_4h", duree_secondes=7200):
        logger.info("[Job 4h] Verrou déjà détenu par un autre worker.")
        return

    try:
        logger.info(f"[Job 4h] Démarrage de l'actualisation globale ({msg}).")
        macro = analyser_tendances_macro()
        rf = obtenir_taux_sans_risque()
        hyp_defaut = normaliser_hypotheses(None)

        today = datetime.today().strftime("%Y-%m-%d")
        conn = _conn_cache()
        try:
            rows = conn.execute(
                "SELECT ticker, indice, last_updated FROM cache_actions WHERE date = ?",
                (today,)
            ).fetchall()
        finally:
            conn.close()

        a_rafraichir = []
        now_utc = datetime.now(timezone.utc)
        for r in rows:
            tk = r["ticker"]
            if "|" in tk:
                continue
            try:
                maj = datetime.fromisoformat((r["last_updated"] or "").replace("Z", "+00:00"))
                if (now_utc - maj).total_seconds() >= 4.0 * 3600:
                    a_rafraichir.append((tk, r["indice"]))
            except Exception:
                a_rafraichir.append((tk, r["indice"]))

        logger.info(f"[Job 4h] {len(a_rafraichir)} action(s) expirée(s) en cache à rafraîchir.")

        def refresh_un(item):
            if _stop_event.is_set():
                return
            tk, idx = item
            bench = obtenir_benchmark(idx) if idx else None
            try:
                analyser_action_brute(tk, [], rf, macro, bench, hyp_defaut, indice=idx)
            except Exception as e:
                logger.warning(f"[Job 4h] Erreur {tk}: {e}")
            time.sleep(random.uniform(0.8, 1.5))

        with ThreadPoolExecutor(max_workers=2) as executor:
            futurs = [executor.submit(refresh_un, item) for item in a_rafraichir]
            for f in as_completed(futurs):
                if _stop_event.is_set():
                    break
                try:
                    f.result()
                except Exception:
                    pass

        logger.info("[Job 4h] Actualisation des indicateurs et actions terminée avec succès.")
    except Exception as e:
        logger.error(f"[Job 4h] Erreur lors de l'actualisation : {e}")
    finally:
        liberer_verrou("job_4h")


def job_staggered_indices():
    ouvert, msg = est_marche_ouvert_ou_recente_cloture()
    if not ouvert:
        logger.info(f"[Job 5h] Ignoré : {msg}.")
        return
    lancer_cycle_asynchrone(max_age_check=3.5)


def demarrer_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    _stop_event.clear()
    _scheduler = BackgroundScheduler(timezone=PARIS_TZ)

    _scheduler.add_job(
        job_mise_a_jour_4h,
        trigger=IntervalTrigger(hours=4, timezone=PARIS_TZ),
        id="job_mise_a_jour_4h",
        replace_existing=True,
        max_instances=1
    )

    _scheduler.add_job(
        job_staggered_indices,
        trigger=IntervalTrigger(hours=5, timezone=PARIS_TZ),
        id="job_staggered_indices",
        replace_existing=True,
        max_instances=1
    )

    _scheduler.start()
    logger.info("Planificateur APScheduler démarré (Rafraîchissement 4h, Staggered 5h).")
    return _scheduler


def arreter_scheduler():
    global _scheduler
    _stop_event.set()
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Planificateur APScheduler arrêté.")