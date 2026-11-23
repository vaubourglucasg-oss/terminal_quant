"""Test de validation complet pour l'évolution d'architecture :
1. Séparation SQLite (données utilisateurs vs cache global)
2. Préférences et favoris utilisateurs (tables et API)
3. Cache global partagé, horodatage UTC et opérations admin
4. Planificateur intelligent et détection des heures de marchés
"""
import os
import sys
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from starlette.testclient import TestClient

# Assurer l'accès aux modules
sys.path.insert(0, os.path.abspath("."))

from app.engine.auth import (init_db, creer_utilisateur, creer_ou_mettre_a_jour_admin,
                             obtenir_preferences, sauvegarder_preferences,
                             obtenir_favoris, ajouter_favori, supprimer_favori, definir_favoris)
from app.engine.fetcher import (init_cache_db, sauvegarder_dans_cache, charger_du_cache,
                                lister_entrees_cache, supprimer_entree_cache,
                                supprimer_cache_indice, vider_cache)
from app.engine.scheduler import est_marche_ouvert_ou_recente_cloture, acquerir_verrou, liberer_verrou
from main import app

def test_sqlite_user_tables():
    print("--- 1. Test des tables et fonctions utilisateurs (users.db) ---")
    init_db()
    # Création d'un utilisateur de test
    email_test = "quant_user_test@domain.com"
    u = creer_utilisateur(email_test, "Password123!")
    user_id = u["id"] if u else 1

    # Préférences
    prefs = {"affichage": {"densite": "compacte", "texte": 110}, "score": {"achat": 80}}
    sauvegarder_preferences(user_id, prefs)
    chargees = obtenir_preferences(user_id)
    assert chargees.get("affichage", {}).get("densite") == "compacte", "Erreur préférence densite"
    print("  [OK] Sauvegarde et chargement des préférences utilisateur.")

    # Favoris
    ajouter_favori(user_id, "MC.PA")
    ajouter_favori(user_id, "AAPL")
    favs = obtenir_favoris(user_id)
    assert "MC.PA" in favs and "AAPL" in favs, "Erreur ajout favoris"

    supprimer_favori(user_id, "AAPL")
    favs2 = obtenir_favoris(user_id)
    assert "AAPL" not in favs2 and "MC.PA" in favs2, "Erreur suppression favori"

    definir_favoris(user_id, ["TTE.PA", "SAN.PA", "NVDA"])
    favs3 = obtenir_favoris(user_id)
    assert favs3 == ["TTE.PA", "SAN.PA", "NVDA"], "Erreur synchronisation globale favoris"
    print("  [OK] Gestion des favoris (ajout, suppression, synchronisation).")


def test_sqlite_cache_global():
    print("\n--- 2. Test du cache global partagé (cache_bourse_v3.db) ---")
    init_cache_db()
    today = datetime.today().strftime("%Y-%m-%d")

    # Sauvegarder avec indice et catégorie
    data_cac = {"ticker": "AI.PA", "nom": "Air Liquide", "prix": 165.5}
    data_sp = {"ticker": "MSFT", "nom": "Microsoft", "prix": 420.0}

    sauvegarder_dans_cache("AI.PA", today, data_cac, indice="CAC 40", categorie="action")
    sauvegarder_dans_cache("MSFT", today, data_sp, indice="S&P 500", categorie="action")

    # Chargement
    charge_ai = charger_du_cache("AI.PA", today)
    assert charge_ai is not None, "Erreur chargement cache AI.PA"
    assert charge_ai["prix"] == 165.5, "Donnée erronée en cache"
    assert "last_updated" in charge_ai, "last_updated manquant dans les données"

    # Liste du cache
    entrees = lister_entrees_cache(50)
    tickers_en_cache = [e["ticker"] for e in entrees]
    assert "AI.PA" in tickers_en_cache and "MSFT" in tickers_en_cache, "Entrées manquantes dans lister_entrees_cache"
    print("  [OK] Sauvegarde, horodatage UTC et listing des entrées en cache.")

    # Suppression par entrée
    suppr_1 = supprimer_entree_cache("AI.PA", today)
    assert suppr_1 >= 1, "Échec suppression entrée unique"
    assert charger_du_cache("AI.PA", today) is None, "AI.PA devrait être supprimé"

    # Suppression par indice
    sauvegarder_dans_cache("MC.PA", today, {"prix": 700}, indice="CAC 40")
    sauvegarder_dans_cache("OR.PA", today, {"prix": 400}, indice="CAC 40")
    suppr_idx = supprimer_cache_indice("CAC 40")
    assert suppr_idx >= 2, "Échec suppression cache par indice"
    print("  [OK] Suppression ciblée (par titre et par indice).")


def test_scheduler_market_hours():
    print("\n--- 3. Test de la détection des heures d'ouverture de marchés ---")
    tz = ZoneInfo("Europe/Paris")

    # 1. Mardi 14h00 (Europe ouverte)
    dt_europe = datetime(2026, 11, 24, 14, 0, tzinfo=tz) # Mardi
    ouvert, msg = est_marche_ouvert_ou_recente_cloture(dt_europe)
    assert ouvert is True, f"Devrait être ouvert pour Europe: {msg}"

    # 2. Mercredi 17h00 (Europe + USA ouvertes)
    dt_double = datetime(2026, 11, 25, 17, 0, tzinfo=tz) # Mercredi
    ouvert, msg = est_marche_ouvert_ou_recente_cloture(dt_double)
    assert ouvert is True, f"Devrait être ouvert: {msg}"

    # 3. Jeudi 04h00 (Asie ouverte)
    dt_asie = datetime(2026, 11, 26, 4, 0, tzinfo=tz) # Jeudi
    ouvert, msg = est_marche_ouvert_ou_recente_cloture(dt_asie)
    assert ouvert is True, f"Devrait être ouvert pour Asie: {msg}"

    # 4. Vendredi 23h50 (Nuit, tous marchés fermés)
    dt_nuit = datetime(2026, 11, 27, 23, 50, tzinfo=tz) # Vendredi tard
    ouvert, msg = est_marche_ouvert_ou_recente_cloture(dt_nuit)
    assert ouvert is False, f"Devrait être fermé la nuit: {msg}"

    # 5. Samedi 14h00 (Week-end fermé)
    dt_we = datetime(2026, 11, 28, 14, 0, tzinfo=tz) # Samedi
    ouvert, msg = est_marche_ouvert_ou_recente_cloture(dt_we)
    assert ouvert is False, f"Devrait être fermé le week-end: {msg}"

    # 6. Verrou anti-doublon
    v1 = acquerir_verrou("test_job", duree_secondes=10)
    assert v1 is True, "Premier verrou devrait être acquis"
    v2 = acquerir_verrou("test_job", duree_secondes=10)
    assert v2 is False, "Deuxième tentative de verrou simultané devrait échouer"
    liberer_verrou("test_job")
    v3 = acquerir_verrou("test_job", duree_secondes=10)
    assert v3 is True, "Verrou libéré devrait pouvoir être réacquis"
    liberer_verrou("test_job")
    print("  [OK] Règles des marchés horaires (Europe, USA, Asie, week-end) et verrou anti-doublon validés.")


def test_api_endpoints():
    print("\n--- 4. Test des endpoints HTTP FastAPI (/api/user et /api/admin) ---")
    admin_email = "admin_master@test.com"
    admin_pass = "AdminSecr3t!"
    creer_ou_mettre_a_jour_admin(admin_email, admin_pass)

    client = TestClient(app)

    # 1. Non authentifié sur /api/user/preferences -> redirection 303 vers /login
    r_unauth = client.get("/api/user/preferences", follow_redirects=False)
    assert r_unauth.status_code == 303, f"Code attendu 303, reçu {r_unauth.status_code}"

    # 2. Connexion
    r_login = client.post("/login", data={"email": admin_email, "password": admin_pass}, follow_redirects=False)
    assert r_login.status_code == 303, f"Échec login: {r_login.status_code}"
    session_cookie = client.cookies.get("tq_session")
    assert session_cookie is not None, "Cookie de session absent après login"

    # 3. GET /api/user/preferences (authentifié)
    r_prefs = client.get("/api/user/preferences")
    assert r_prefs.status_code == 200, f"Code 200 attendu: {r_prefs.status_code}"

    # 4. POST /api/user/preferences
    r_post_pref = client.post("/api/user/preferences", json={"affichage": {"daltonien": True}})
    assert r_post_pref.status_code == 200
    assert r_post_pref.json()["preferences"]["affichage"]["daltonien"] is True

    # 5. POST & GET /api/user/favorites
    r_fav_add = client.post("/api/user/favorites", json={"ticker": "BNP.PA", "action": "add"})
    assert r_fav_add.status_code == 200
    assert "BNP.PA" in r_fav_add.json()["favorites"]

    r_fav_list = client.get("/api/user/favorites")
    assert "BNP.PA" in r_fav_list.json()["favorites"]

    # 6. Admin cache endpoints
    r_cache_list = client.get("/api/admin/cache/entries")
    assert r_cache_list.status_code == 200
    assert "entries" in r_cache_list.json()

    r_cache_del_entry = client.delete("/api/admin/cache/entry?ticker=MSFT")
    assert r_cache_del_entry.status_code == 200

    r_cache_del_all = client.delete("/api/admin/cache/all")
    assert r_cache_del_all.status_code == 200
    assert r_cache_del_all.json()["status"] == "ok"
    print("  [OK] Tous les endpoints /api/user et /api/admin fonctionnent parfaitement.")

if __name__ == "__main__":
    try:
        test_sqlite_user_tables()
        test_sqlite_cache_global()
        test_scheduler_market_hours()
        test_api_endpoints()
        print("\n=== TOUS LES TESTS SONT PASSÉS AVEC SUCCÈS (100%) ===")
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
