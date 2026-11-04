from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.screener import router as api_router

app = FastAPI(
    title="Terminal Quantitatif",
    description="Screener boursier : valorisation, qualité, risque et momentum",
    version="2.0.0",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(api_router)

if __name__ == "__main__":
    import uvicorn
    print("Démarrage du terminal sur http://127.0.0.1:8000 ...")
    # "main:app" (module:objet) — l'ancien "main.py" n'est pas un chemin d'import valide pour uvicorn.
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
