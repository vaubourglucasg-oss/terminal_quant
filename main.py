from fastapi import FastAPI
from app.api.screener import router as api_router
from fastapi import Request

app = FastAPI(
    title="Terminal Quantitatif SaaS",
    description="Moteur d'analyse boursière temps réel",
    version="1.0.0"
)

app.include_router(api_router)

if __name__ == "__main__":
    import uvicorn
    print("🚀 Démarrage du Terminal sur http://127.0.0.1:8000 ...")
    uvicorn.run("main.py", host="127.0.0.1", port=8000, reload=True)

@app.middleware("http")
async def desactiver_cache_navigateur(request: Request, call_next):
    response = await call_next(request)
    # On force le navigateur de l'utilisateur à toujours recharger la page
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response