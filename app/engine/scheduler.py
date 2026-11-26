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
                                normaliser_hypotheses, _conn_cache,
                                vider_staging, valider_staging_vers_cache,
                                lire_meta, ecrire_meta)
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
DELAI_ENTRE_INDICES_SEC = 5

_scheduler = None
_stop_event = threading.Event()


def _maj_etat_refresh(**kwargs):
    etat = lire_meta("etat_refresh") or {
        "en_cours": False,
        "mode": "",
        "cible": "",
        "faits": 0,
        "total": 0,
        "reussis": 0,
        "echecs": 0,
        "debut": None,
        "fin": None,
        "derniere_bascule": None,
        "heartbeat": 0,
    }
    etat.update(kwargs)
    etat["heartbeat"] = time.time()
    ecrire_meta("etat_refresh", etat)
    return etat


def obtenir_etat_refresh() -> dict:
    etat = lire_meta("etat_refresh") or {
        "en_cours": False,
        "mode": "",
        "cible": "",
        "faits": 0,
        "total": 0,
        "reussis": 0,
        "echecs": 0,
        "debut": None,
        "fin": None,
        "derniere_bascule": None,
        "heartbeat": 0,
    }
    # Si un conteneur Cloud Run a été coupé sans finir, réinitialise l'affichage après 4 min d'inactivité
    if etat.get("en_cours") and (time.time() - float(etat.get("heartbeat") or 0)) > 240:
        etat["en_cours"] = False
    return etat


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


def prolonger_verrou(job_id: str, duree_secondes: int = 300):
    try:
        conn = _conn_cache()
        conn.execute("UPDATE scheduler_locks SET expire_le = ? WHERE job_id = ?",
                     (time.time() + duree_secondes, job_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


def acquerir_verrou(job_id: str, duree_secondes: int = 300) -> bool:
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
        conn.execute("DELETE FROM scheduler_locks WHERE job_id = ?", (job_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Erreur libération verrou {job_id} : {e}")


def _charger_un_indice_vers_staging(nom_indice: str, rf: float, macro: dict, hyp: dict, compteur: dict) -> int:
    bench = obtenir_benchmark(nom_indice)
    tickers = list(dict.fromkeys(obtenir_tickers_pour_indice(nom_indice)))
    logger.info(f"[{nom_indice}] Chargement vers staging de {len(tickers)} titres.")
    reussis_indice = 0

    def worker_action(tk):
        if _stop_event.is_set():
            return None
        try:
            res = analyser_action_brute(
                tk, [], rf, macro, bench, hyp,
                indice=nom_indice, table_cible="cache_actions_staging"
            )
        except Exception as e:
            logger.warning(f"[{nom_indice}] Erreur {tk}: {e}")
            res = None
        time.sleep(random.uniform(0.35, 0.75))
        return res

    with ThreadPoolExecutor(max_workers=3) as executor:
        futurs = [executor.submit(worker_action, tk) for tk in tickers]
        for f in as_completed(futurs):
            if _stop_event.is_set():
                break
            res = None
            try:
                res = f.result()
            except Exception:
                pass
            compteur["faits"] += 1
            if res is not None:
                compteur["reussis"] += 1
                reussis_indice += 1
            else:
                compteur["echecs"] += 1
            if compteur["faits"] % 10 == 0 or compteur["faits"] == compteur["total"]:
                prolonger_verrou("cycle_complet", 300)
                _maj_etat_refresh(
                    cible=nom_indice,
                    faits=compteur["faits"],
                    total=compteur["total"],
                    reussis=compteur["reussis"],
                    echecs=compteur["echecs"],
                )
    return reussis_indice


def executer_liste_indices_atomique(indices: list[str], mode: str) -> int:
    """Charge chaque indice en staging puis le bascule atomiquement dès qu'il est complet."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tous_tickers = [tk for idx in indices for tk in obtenir_tickers_pour_indice(idx)]
    compteur = {"faits": 0, "total": len(tous_tickers), "reussis": 0, "echecs": 0}
    total_bascules = 0

    _maj_etat_refresh(
        en_cours=True, mode=mode, cible=indices[0] if indices else "",
        faits=0, total=len(tous_tickers), reussis=0, echecs=0,
        debut=now_iso, fin=None
    )

    try:
        rf = obtenir_taux_sans_risque(forcer_yahoo=True)
        macro = analyser_tendances_macro(forcer_yahoo=True)
        hyp_defaut = normaliser_hypotheses(None)

        for i, nom_indice in enumerate(indices):
            if _stop_event.is_set():
                logger.info(f"[{mode}] Arrêt prématuré demandé.")
                break

            if i > 0:
                time.sleep(DELAI_ENTRE_INDICES_SEC)

            prolonger_verrou("cycle_complet", 300)
            _maj_etat_refresh(cible=nom_indice)
            try:
                vider_staging([nom_indice])
                _charger_un_indice_vers_staging(nom_indice, rf, macro, hyp_defaut, compteur)
                # Bascule atomique immédiate pour cet indice dès que tous ses titres sont prêts
                nb = valider_staging_vers_cache([nom_indice])
                total_bascules += nb
                bascule_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                logger.info(f"[{mode}] {nom_indice} basculé atomiquement ({nb} titres).")
                _maj_etat_refresh(derniere_bascule=f"{bascule_iso} ({nom_indice} : {nb} titres)")
            except Exception as e:
                logger.error(f"[{mode}] Erreur sur {nom_indice} : {e}")

        fin_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _maj_etat_refresh(
            en_cours=False, faits=compteur["faits"], total=compteur["total"],
            reussis=compteur["reussis"], echecs=compteur["echecs"],
            fin=fin_iso, derniere_bascule=f"{fin_iso} (Total : {total_bascules} titres)"
        )
        return total_bascules
    except Exception as e:
        logger.error(f"[{mode}] Échec global : {e}")
        _maj_etat_refresh(en_cours=False, fin=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        return total_bascules


def lancer_cycle_asynchrone(mode: str = "Scheduler") -> bool:
    """Lance la mise à jour complète des 20 indices en arrière-plan."""
    if not acquerir_verrou("cycle_complet", duree_secondes=300):
        logger.info("[Scheduler] Une mise à jour est déjà en cours, appel ignoré.")
        return False

    def runner():
        try:
            executer_liste_indices_atomique(TOUS_LES_INDICES, mode=mode)
        finally:
            liberer_verrou("cycle_complet")

    thread = threading.Thread(target=runner, daemon=True, name="cron-cycle-worker")
    thread.start()
    return True


def lancer_indice_asynchrone(nom_indice: str) -> bool:
    """Lance le rechargement manuel d'un seul indice depuis l'interface Admin."""
    if nom_indice not in TOUS_LES_INDICES:
        return False
    if not acquerir_verrou("cycle_complet", duree_secondes=300):
        logger.info(f"[Admin] Impossible de lancer {nom_indice} : un chargement est déjà en cours.")
        return False

    def runner():
        try:
            executer_liste_indices_atomique([nom_indice], mode=f"Admin ({nom_indice})")
        finally:
            liberer_verrou("cycle_complet")

    thread = threading.Thread(target=runner, daemon=True, name=f"admin-refresh-{nom_indice}")
    thread.start()
    return True


def job_staggered_indices():
    ouvert, msg = est_marche_ouvert_ou_recente_cloture()
    if not ouvert:
        logger.info(f"[Job auto] Ignoré : {msg}.")
        return
    lancer_cycle_asynchrone(mode="Scheduler auto")


def demarrer_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    _stop_event.clear()
    _scheduler = BackgroundScheduler(timezone=PARIS_TZ)

    _scheduler.add_job(
        job_staggered_indices,
        trigger=IntervalTrigger(hours=5, timezone=PARIS_TZ),
        id="job_staggered_indices",
        replace_existing=True,
        max_instances=1
    )

    _scheduler.start()
    logger.info("Planificateur APScheduler démarré (cycle atomique par indice toutes les 5h).")
    return _scheduler


def arreter_scheduler():
    global _scheduler
    _stop_event.set()
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Planificateur APScheduler arrêté.")