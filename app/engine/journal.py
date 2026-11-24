"""Journal des signaux : mémoire immuable de ce que le score a affirmé, jour après jour.

POURQUOI. Pour savoir si le score est bon, il faut le comparer à ce qui s'est réellement passé ensuite. Les
fondamentaux de Yahoo ne sont que ceux d'aujourd'hui : on ne peut pas rejouer le passé sans tricher. La seule mesure
honnête est donc d'enregistrer chaque classement au moment où il est produit, puis d'attendre.

CE QUI EST ENREGISTRÉ. Un instantané (table `scans`) par jour, par indice et par version du calcul, avec une ligne
par titre (table `signaux`) : prix, score, signal, les 5 facteurs, la sévérité de baisse et le régime (si le calcul les
fournit). Seuls les scans STANDARD sont enregistrés (sinon les classements ne seraient pas comparables entre eux) :
  • aucun filtre de secteur (un classement dans un seul secteur n'a pas le même sens) ;
  • hypothèses de valorisation par défaut (sinon la marge de sécurité n'est pas la même) ;
  • au moins 80 % des titres de l'indice analysés (un scan tronqué fausse les rangs).
Les réglages du score (pondérations, seuils) sont ceux par défaut : le classement est recalculé ici avec eux, quels que
soient les curseurs de l'utilisateur.

VERSION DU CALCUL. `version_calcul` est une empreinte du code de scoring.py, math_models.py et fetcher.py : elle change
toute seule dès qu'une formule change. Tu peux ainsi comparer l'ancien et le nouveau calcul sur des données réelles.

IMMUABILITÉ. Des déclencheurs SQLite refusent toute modification ou suppression. Ce n'est pas une preuve d'audit : celui
qui a accès au fichier peut retirer les déclencheurs. Pour un historique opposable à des clients, il faudra en plus
publier régulièrement une empreinte du journal chez un tiers (voir le guide).

La base est un fichier À PART du cache (cache_bourse_v3.db) : « Vider le cache » ou un changement de VERSION_SCHEMA ne
peuvent pas l'effacer. À sauvegarder comme n'importe quelle donnée de valeur ; ne pas la versionner dans git.
"""
import csv
import hashlib
import io
import math
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone

from app.engine.scoring import calculer_scores, normaliser_reglages

_dossier = os.path.dirname(os.path.abspath(__file__))
racine = os.path.dirname(os.path.dirname(_dossier))
DATA_DIR = os.environ.get("DATA_DIR") or racine
os.makedirs(DATA_DIR, exist_ok=True)
db_journal_path = os.environ.get("JOURNAL_DB") or os.path.join(DATA_DIR, "journal_signaux.db")

SEUIL_COMPLET = 0.8          # part minimale des titres demandés qui doivent avoir été analysés
MIN_TITRES = 10
FICHIERS_CALCUL = ("scoring.py", "math_models.py", "fetcher.py")
_verrou = threading.Lock()
_version = None

COLONNES_EXPORT = ("jour", "cree_le", "indice", "version_calcul", "ticker", "nom", "secteur", "devise", "prix",
                   "score", "signal", "valo", "qual", "crois", "risq", "mom", "couverture", "severite", "regime")

_DDL = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jour TEXT NOT NULL,                 -- date UTC du scan (AAAA-MM-JJ)
    indice TEXT NOT NULL,
    version_calcul TEXT NOT NULL,
    version_schema INTEGER,
    cree_le TEXT NOT NULL,              -- horodatage UTC
    nb_titres INTEGER NOT NULL,         -- titres enregistrés
    nb_demandes INTEGER NOT NULL,       -- titres de l'indice
    UNIQUE (jour, indice, version_calcul)
);
CREATE TABLE IF NOT EXISTS signaux (
    scan_id INTEGER NOT NULL REFERENCES scans(id),
    ticker TEXT NOT NULL, nom TEXT, secteur TEXT, devise TEXT, prix REAL,
    score INTEGER, signal TEXT NOT NULL,
    valo INTEGER, qual INTEGER, crois INTEGER, risq INTEGER, mom INTEGER, couverture INTEGER,
    severite REAL, regime TEXT,
    PRIMARY KEY (scan_id, ticker)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_scans_jour ON scans(jour);
CREATE TRIGGER IF NOT EXISTS scans_pas_de_modif BEFORE UPDATE ON scans BEGIN SELECT RAISE(ABORT, 'journal immuable'); END;
CREATE TRIGGER IF NOT EXISTS scans_pas_de_suppr BEFORE DELETE ON scans BEGIN SELECT RAISE(ABORT, 'journal immuable'); END;
CREATE TRIGGER IF NOT EXISTS signaux_pas_de_modif BEFORE UPDATE ON signaux BEGIN SELECT RAISE(ABORT, 'journal immuable'); END;
CREATE TRIGGER IF NOT EXISTS signaux_pas_de_suppr BEFORE DELETE ON signaux BEGIN SELECT RAISE(ABORT, 'journal immuable'); END;
"""


def _connexion():
    dossier = os.path.dirname(db_journal_path)
    if dossier:
        os.makedirs(dossier, exist_ok=True)
    conn = sqlite3.connect(db_journal_path, timeout=30, isolation_level=None)   # transactions gérées à la main
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_DDL)
    return conn


def version_calcul():
    """Empreinte (10 caractères) du code de calcul. Les fins de ligne sont normalisées : même valeur sous Windows et Linux."""
    global _version
    if _version is None:
        h = hashlib.sha256()
        for nom in FICHIERS_CALCUL:
            chemin = os.path.join(_dossier, nom)
            if os.path.exists(chemin):
                with open(chemin, "rb") as f:
                    h.update(nom.encode() + b"\n" + f.read().replace(b"\r\n", b"\n"))
        _version = h.hexdigest()[:10]
    return _version


def _version_schema():
    try:
        with open(os.path.join(_dossier, "fetcher.py"), encoding="utf-8") as f:
            m = re.search(r"^VERSION_SCHEMA\s*=\s*(\d+)", f.read(), re.M)
        return int(m.group(1)) if m else None
    except OSError:
        return None


def _num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else x


def _entier(x):
    x = _num(x)
    return None if x is None else int(round(x))


def _texte(x):
    return None if x is None else str(x)


def journaliser_scan(indice, lignes, nb_demandes, secteurs_cibles=(), hyp_defaut=True):
    """Enregistre l'instantané d'un scan s'il est standard et complet. Ne lève JAMAIS d'exception (le flux d'analyse
    ne doit pas dépendre du journal). Retourne (enregistre: bool, raison: str)."""
    try:
        if secteurs_cibles:
            return False, "scan filtré par secteur : classement non comparable"
        if not hyp_defaut:
            return False, "hypothèses de valorisation modifiées : classement non comparable"
        propres = {}
        for l in lignes or []:
            if isinstance(l, dict) and l.get("ticker") and not l.get("erreur_ticker"):
                propres[str(l["ticker"])] = l
        if len(propres) < MIN_TITRES or len(propres) < SEUIL_COMPLET * max(int(nb_demandes or 0), 1):
            return False, f"scan incomplet ({len(propres)} titres sur {nb_demandes})"

        scores = calculer_scores(list(propres.values()), normaliser_reglages(None))
        jour = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        maintenant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ver = version_calcul()
        with _verrou:
            conn = _connexion()
            try:
                conn.execute("BEGIN IMMEDIATE")
                deja = conn.execute("SELECT id FROM scans WHERE jour=? AND indice=? AND version_calcul=?",
                                    (jour, indice, ver)).fetchone()
                if deja:
                    conn.execute("ROLLBACK")
                    return False, "déjà enregistré aujourd'hui pour cette version du calcul"
                cur = conn.execute("INSERT INTO scans (jour, indice, version_calcul, version_schema, cree_le, nb_titres, nb_demandes) "
                                   "VALUES (?,?,?,?,?,?,?)",
                                   (jour, indice, ver, _version_schema(), maintenant, len(propres), int(nb_demandes)))
                scan_id = cur.lastrowid
                rows = []
                for tk, l in propres.items():
                    s = scores.get(tk) or {}
                    rows.append((scan_id, tk, _texte(l.get("nom")), _texte(l.get("secteur")), _texte(l.get("devise")),
                                 _num(l.get("prix")), _entier(s.get("score")), s.get("signal") or "INCONNU",
                                 _entier(s.get("valo")), _entier(s.get("qual")), _entier(s.get("crois")),
                                 _entier(s.get("risq")), _entier(s.get("mom")), _entier(s.get("couverture")),
                                 _num(s.get("severite")), _texte(s.get("regime"))))
                conn.executemany("INSERT INTO signaux VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                conn.close()
        return True, f"{len(rows)} signaux enregistrés (version {ver})"
    except Exception as e:
        return False, f"erreur du journal : {type(e).__name__} {e}"


def resume():
    """Vue d'ensemble pour vérifier que le journal se remplit."""
    conn = _connexion()
    try:
        n_scans, premier, dernier = conn.execute("SELECT COUNT(*), MIN(jour), MAX(jour) FROM scans").fetchone()
        n_signaux = conn.execute("SELECT COUNT(*) FROM signaux").fetchone()[0]
        par_indice = [dict(indice=i, scans=n, premier_jour=a, dernier_jour=b) for i, n, a, b in
                      conn.execute("SELECT indice, COUNT(*), MIN(jour), MAX(jour) FROM scans GROUP BY indice ORDER BY indice")]
        par_version = [dict(version=v, scans=n, premier_jour=a, dernier_jour=b) for v, n, a, b in
                       conn.execute("SELECT version_calcul, COUNT(*), MIN(jour), MAX(jour) FROM scans "
                                    "GROUP BY version_calcul ORDER BY MIN(cree_le)")]
        derniers = [dict(jour=j, indice=i, titres=n, demandes=d, version=v) for j, i, n, d, v in
                    conn.execute("SELECT jour, indice, nb_titres, nb_demandes, version_calcul FROM scans ORDER BY id DESC LIMIT 10")]
    finally:
        conn.close()
    return {"scans": n_scans, "signaux": n_signaux, "premier_jour": premier, "dernier_jour": dernier,
            "version_actuelle": version_calcul(), "par_indice": par_indice, "par_version": par_version,
            "derniers_scans": derniers}


def _cellule(x):
    """Neutralise l'injection de formules dans Excel / LibreOffice (cellule texte commençant par = + - @)."""
    if isinstance(x, str) and x[:1] in ("=", "+", "-", "@"):
        return "'" + x
    return x


def exporter_csv(indice="", depuis=""):
    """Tout le journal (ou un indice, ou depuis une date AAAA-MM-JJ) en CSV UTF-8 avec BOM, lisible par Excel."""
    sql = ("SELECT s.jour, s.cree_le, s.indice, s.version_calcul, g.ticker, g.nom, g.secteur, g.devise, g.prix, g.score, "
           "g.signal, g.valo, g.qual, g.crois, g.risq, g.mom, g.couverture, g.severite, g.regime "
           "FROM signaux g JOIN scans s ON s.id = g.scan_id WHERE 1=1")
    params = []
    if indice:
        sql += " AND s.indice = ?"
        params.append(indice)
    if depuis:
        sql += " AND s.jour >= ?"
        params.append(depuis)
    sql += " ORDER BY s.jour, s.indice, g.ticker"
    conn = _connexion()
    try:
        lignes = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    sortie = io.StringIO()
    w = csv.writer(sortie)
    w.writerow(COLONNES_EXPORT)
    for ligne in lignes:
        w.writerow([_cellule(c) for c in ligne])
    return "\ufeff" + sortie.getvalue()
