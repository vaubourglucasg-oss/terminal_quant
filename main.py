import os
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.api.screener import router as api_router

app = FastAPI(
    title="Terminal Quantitatif SaaS",
    description="Moteur d'analyse boursière temps réel",
    version="1.0.0"
)

# Servir le dossier app/templates pour le CSS et les fichiers statiques
app.mount("/static", StaticFiles(directory="app/templates"), name="static")

app.include_router(api_router)

# ROUTE 1 : Page de Connexion (Affichée en premier)
@app.get("/")
async def read_root():
    return FileResponse("app/templates/Login.html")

# ROUTE 2 : Page d'Inscription
@app.get("/register")
async def read_register():
    return FileResponse("app/templates/register.html")

# ROUTE 3 : Redirection vers le screener / dashboard
@app.get("/dashboard")
async def read_dashboard():
    return FileResponse("app/templates/index.html")

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