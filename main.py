import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.api.screener import router as api_router

app = FastAPI(
    title="Terminal Quantitatif SaaS",
    description="Moteur d'analyse boursière temps réel",
    version="1.0.0"
)

# Chemin absolu dynamique (indépendant du répertoire d'exécution de Docker)
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "app" / "templates"

if not TEMPLATES_DIR.exists():
    TEMPLATES_DIR = BASE_DIR / "templates"

app.mount("/static", StaticFiles(directory=str(TEMPLATES_DIR)), name="static")

# Helper pour trouver un fichier HTML quelle que soit sa casse
def trouver_template(nom_fichier: str) -> Path:
    f = TEMPLATES_DIR / nom_fichier
    if f.exists():
        return f
    # Alternative avec majuscule
    f_cap = TEMPLATES_DIR / nom_fichier.capitalize()
    if f_cap.exists():
        return f_cap
    raise FileNotFoundError(f"Fichier {nom_fichier} introuvable dans {TEMPLATES_DIR}")

@app.get("/")
async def read_root():
    fichier = trouver_template("login.html")
    return FileResponse(str(fichier))

@app.get("/register")
async def read_register():
    fichier = trouver_template("register.html")
    return FileResponse(str(fichier))

app.include_router(api_router)

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