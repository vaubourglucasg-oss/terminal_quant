import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from app.api.screener import router as api_router
from app.api.mindmap_routes import router as mindmap_router  # juste sous l'import de api_router
from app.api.journal_routes import router as journal_router
from app.api.auth_routes import router as auth_router
from app.api.admin_routes import router as admin_router
from app.engine.auth import init_db, creer_ou_mettre_a_jour_admin

# Configuration du compte administrateur et de la session
ADMIN_EMAIL_DEFAUT = "vaubourg.lucasg@gmail.com"
ADMIN_PASSWORD_DEFAUT = "Lucas.a380"

os.environ.setdefault("ADMIN_EMAIL", ADMIN_EMAIL_DEFAUT)
os.environ.setdefault("SESSION_SECRET", os.environ.get("SESSION_SECRET", "Lucas.a380"))

app = FastAPI(
    title="Terminal Quantitatif SaaS",
    description="Moteur d'analyse boursière temps réel",
    version="1.0.0"
)

# Clé secrète pour signer les sessions (cookie HttpOnly)
SESSION_SECRET = os.environ.get("SESSION_SECRET", "Lucas.a380")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="tq_session",
    max_age=7 * 24 * 3600,
    https_only=False,
    same_site="lax"
)

BASE_DIR = Path(__file__).resolve().parent

# FIXATION DU DOSSIER STATIQUE : Pointer vers app/static (et non app/templates)
STATIC_DIR = BASE_DIR / "app" / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(api_router)
app.include_router(mindmap_router)
app.include_router(journal_router)

# Initialiser la base utilisateurs et enregistrer/mettre à jour l'administrateur
init_db()
creer_ou_mettre_a_jour_admin(ADMIN_EMAIL_DEFAUT, ADMIN_PASSWORD_DEFAUT)

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
