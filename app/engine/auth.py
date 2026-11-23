"""Gestion des utilisateurs : base SQLite séparée (users.db), hashage bcrypt, sessions signées.

Ce module fournit :
  - init_db()         : crée la table users si elle n'existe pas
  - creer_utilisateur : inscription
  - authentifier      : vérification identifiants
  - get_current_user  : dépendance FastAPI (extrait l'utilisateur de la session)
  - require_admin     : dépendance FastAPI (403 si pas admin)
"""
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

import bcrypt

racine = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.environ.get("USERS_DB") or os.path.join(racine, "users.db")


def hacher_mot_de_passe(mot_de_passe: str) -> str:
    """Hache un mot de passe avec bcrypt (12 rounds)."""
    pwd_bytes = mot_de_passe.encode("utf-8")[:72]
    sel = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pwd_bytes, sel).decode("utf-8")


def verifier_mot_de_passe(mot_de_passe: str, hache: str) -> bool:
    """Vérifie si le mot de passe correspond au hash bcrypt."""
    try:
        pwd_bytes = mot_de_passe.encode("utf-8")[:72]
        return bcrypt.checkpw(pwd_bytes, hache.encode("utf-8"))
    except Exception:
        return False

_verrou = threading.Lock()

_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    cree_le TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id INTEGER PRIMARY KEY,
    preferences_json TEXT NOT NULL,
    mis_a_jour_le TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_favorites (
    user_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    ajoute_le TEXT NOT NULL,
    PRIMARY KEY (user_id, ticker),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""


def _conn():
    dossier = os.path.dirname(DB_PATH)
    if dossier:
        os.makedirs(dossier, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def admin_email_configure() -> str:
    """Récupère dynamiquement l'adresse admin configurée dans l'environnement."""
    return os.environ.get("ADMIN_EMAIL", "").strip().lower()


def init_db():
    """Initialise la base au démarrage de l'application et crée la table si elle n'existe pas."""
    with _verrou:
        conn = _conn()
        try:
            conn.executescript(_DDL)
        finally:
            conn.close()


def creer_ou_mettre_a_jour_admin(email: str, mot_de_passe: str) -> dict:
    """Crée ou met à jour le compte administrateur avec le mot de passe fourni."""
    email = email.strip().lower()
    hache = hacher_mot_de_passe(mot_de_passe)
    maintenant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _verrou:
        conn = _conn()
        try:
            existant = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if existant:
                conn.execute("UPDATE users SET password_hash = ?, role = 'admin' WHERE email = ?", (hache, email))
            else:
                conn.execute("INSERT INTO users (email, password_hash, role, cree_le) VALUES (?, ?, 'admin', ?)",
                             (email, hache, maintenant))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            return dict(row)
        finally:
            conn.close()


def creer_utilisateur(email: str, mot_de_passe: str) -> dict | None:
    """Crée un utilisateur. Retourne le dict utilisateur ou None si l'email existe déjà.
    Le premier utilisateur inscrit ou l'adresse ADMIN_EMAIL obtient automatiquement le rôle admin.
    """
    email = email.strip().lower()
    hache = hacher_mot_de_passe(mot_de_passe)
    admin_cible = admin_email_configure()
    maintenant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _verrou:
        conn = _conn()
        try:
            nb_existants = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            # Le premier utilisateur inscrit devient automatiquement admin, ou si l'email correspond à ADMIN_EMAIL
            role = "admin" if (nb_existants == 0 or (admin_cible and email == admin_cible)) else "user"
            conn.execute("INSERT INTO users (email, password_hash, role, cree_le) VALUES (?, ?, ?, ?)",
                         (email, hache, role, maintenant))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            return dict(row) if row else None
        except sqlite3.IntegrityError:
            return None
        finally:
            conn.close()


def authentifier(email: str, mot_de_passe: str) -> dict | None:
    """Vérifie les identifiants. Retourne le dict utilisateur ou None."""
    email = email.strip().lower()
    admin_cible = admin_email_configure()
    with _verrou:
        conn = _conn()
        try:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if row and verifier_mot_de_passe(mot_de_passe, row["password_hash"]):
                # S'assurer que le rôle admin est bien attribué si c'est l'admin cible ou le seul utilisateur
                nb_total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                if row["role"] != "admin" and (nb_total == 1 or (admin_cible and email == admin_cible)):
                    conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (row["id"],))
                    conn.commit()
                    row = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
                return dict(row)
        finally:
            conn.close()
    return None


def lister_utilisateurs() -> list[dict]:
    """Liste tous les utilisateurs (sans le hash)."""
    with _verrou:
        conn = _conn()
        try:
            rows = conn.execute("SELECT id, email, role, cree_le FROM users ORDER BY id").fetchall()
        finally:
            conn.close()
    return [dict(r) for r in rows]


def get_user_by_id(user_id: int) -> dict | None:
    """Récupère un utilisateur par son ID."""
    with _verrou:
        conn = _conn()
        try:
            row = conn.execute("SELECT id, email, role, cree_le FROM users WHERE id = ?", (user_id,)).fetchone()
        finally:
            conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Préférences et Watchlist (Favoris) liés au compte utilisateur
# ---------------------------------------------------------------------------
def obtenir_preferences(user_id: int) -> dict:
    """Récupère les préférences de l'utilisateur ou un dictionnaire vide si aucune."""
    with _verrou:
        conn = _conn()
        try:
            row = conn.execute("SELECT preferences_json FROM user_preferences WHERE user_id = ?", (user_id,)).fetchone()
            if row and row["preferences_json"]:
                return json.loads(row["preferences_json"])
        except Exception:
            pass
        finally:
            conn.close()
    return {}


def sauvegarder_preferences(user_id: int, prefs: dict) -> dict:
    """Enregistre ou met à jour les préférences de l'utilisateur."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    texte = json.dumps(prefs)
    with _verrou:
        conn = _conn()
        try:
            conn.execute("""
                INSERT INTO user_preferences (user_id, preferences_json, mis_a_jour_le)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    preferences_json = excluded.preferences_json,
                    mis_a_jour_le = excluded.mis_a_jour_le
            """, (user_id, texte, now_iso))
            conn.commit()
        finally:
            conn.close()
    return prefs


def obtenir_favoris(user_id: int) -> list[str]:
    """Liste les tickers favoris de l'utilisateur."""
    with _verrou:
        conn = _conn()
        try:
            rows = conn.execute("SELECT ticker FROM user_favorites WHERE user_id = ? ORDER BY rowid ASC",
                                (user_id,)).fetchall()
            return [r["ticker"] for r in rows]
        finally:
            conn.close()


def ajouter_favori(user_id: int, ticker: str) -> bool:
    """Ajoute un ticker aux favoris de l'utilisateur."""
    tk = ticker.strip().upper()
    if not tk:
        return False
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _verrou:
        conn = _conn()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO user_favorites (user_id, ticker, ajoute_le)
                VALUES (?, ?, ?)
            """, (user_id, tk, now_iso))
            conn.commit()
            return True
        finally:
            conn.close()


def supprimer_favori(user_id: int, ticker: str) -> bool:
    """Retire un ticker des favoris de l'utilisateur."""
    tk = ticker.strip().upper()
    if not tk:
        return False
    with _verrou:
        conn = _conn()
        try:
            conn.execute("DELETE FROM user_favorites WHERE user_id = ? AND ticker = ?", (user_id, tk))
            conn.commit()
            return True
        finally:
            conn.close()


def definir_favoris(user_id: int, tickers: list[str]) -> list[str]:
    """Remplace complètement la liste des favoris de l'utilisateur."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    propres = list(dict.fromkeys([t.strip().upper() for t in tickers if t and t.strip()]))
    with _verrou:
        conn = _conn()
        try:
            conn.execute("DELETE FROM user_favorites WHERE user_id = ?", (user_id,))
            for tk in propres:
                conn.execute("INSERT INTO user_favorites (user_id, ticker, ajoute_le) VALUES (?, ?, ?)",
                             (user_id, tk, now_iso))
            conn.commit()
            return propres
        finally:
            conn.close()

