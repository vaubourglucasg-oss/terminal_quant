import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from app.api.screener import router as api_router

app = FastAPI(
    title="Terminal Quantitatif SaaS",
    description="Moteur d'analyse boursière temps réel",
    version="1.0.0"
)

BASE_DIR = Path(__file__).resolve().parent

# FIXATION DU DOSSIER STATIQUE : Pointer vers app/static (et non app/templates)
STATIC_DIR = BASE_DIR / "app" / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

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