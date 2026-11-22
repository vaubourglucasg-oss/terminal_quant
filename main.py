import os
import secrets
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from app.api.screener import router as api_router
from app.api.mindmap_routes import router as mindmap_router
from app.api.journal_routes import router as journal_router
from app.api.auth_routes import router as auth_router
from app.api.admin_routes import router as admin_router
from app.engine.auth import init_db, creer_ou_mettre_a_jour_admin

BASE_DIR = Path(__file__).resolve().parent

# Chargement automatique du fichier .env si présent (local ou volume monté)
env_path = BASE_DIR / ".env"
if env_path.exists():
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass

# Configuration via variables d'environnement
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()
SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)

app = FastAPI(
    title="Terminal Quantitatif SaaS",
    description="Moteur d'analyse boursière temps réel",
    version="1.0.0"
)

# Gestion sécurisée des sessions (cookie HttpOnly signé)
HTTPS_ONLY = os.environ.get("HTTPS_ONLY", "false").lower() in ("true", "1")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="tq_session",
    max_age=7 * 24 * 3600,
    https_only=HTTPS_ONLY,
    same_site="lax"
)

# Montage des fichiers statiques
STATIC_DIR = BASE_DIR / "app" / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Enregistrement des routes modulaires
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(api_router)
app.include_router(mindmap_router)
app.include_router(journal_router)

# Initialisation de la base utilisateurs et synchronisation du compte admin si configuré
init_db()
if ADMIN_EMAIL and ADMIN_PASSWORD:
    creer_ou_mettre_a_jour_admin(ADMIN_EMAIL, ADMIN_PASSWORD)

@app.middleware("http")
async def desactiver_cache_navigateur(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
