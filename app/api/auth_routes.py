"""Routes d'authentification : connexion, inscription, déconnexion.

Sessions gérées via cookie HttpOnly signé (SessionMiddleware de Starlette).
Dépendances réutilisables : get_current_user, require_admin.
"""
import re
from pathlib import Path

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.engine.auth import authentifier, creer_utilisateur, get_user_by_id

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

RE_EMAIL = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


# ---------------------------------------------------------------------------
# Dépendances réutilisables
# ---------------------------------------------------------------------------
async def get_current_user(request: Request) -> dict | None:
    """Retourne l'utilisateur connecté ou None."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return get_user_by_id(user_id)


async def require_login(request: Request) -> dict:
    """Exige un utilisateur connecté, sinon redirige vers /login."""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


async def require_admin(request: Request) -> dict:
    """Exige le rôle admin, sinon 403."""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")
    return user


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = await get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"erreur": ""})


@router.post("/login", response_class=HTMLResponse)
async def login_post(request: Request):
    form = await request.form()
    email = str(form.get("email", "")).strip()
    mot_de_passe = str(form.get("password", ""))

    if not email or not mot_de_passe:
        return templates.TemplateResponse(request=request, name="login.html",
                                          context={"erreur": "Veuillez remplir tous les champs."})

    user = authentifier(email, mot_de_passe)
    if not user:
        return templates.TemplateResponse(request=request, name="login.html",
                                          context={"erreur": "Identifiants incorrects."})

    request.session["user_id"] = user["id"]
    request.session["user_email"] = user["email"]
    request.session["user_role"] = user["role"]
    return RedirectResponse("/", status_code=303)


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    user = await get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="register.html", context={"erreur": ""})


@router.post("/register", response_class=HTMLResponse)
async def register_post(request: Request):
    form = await request.form()
    email = str(form.get("email", "")).strip()
    mot_de_passe = str(form.get("password", ""))
    confirmation = str(form.get("password_confirm", ""))

    if not email or not mot_de_passe or not confirmation:
        return templates.TemplateResponse(request=request, name="register.html",
                                          context={"erreur": "Veuillez remplir tous les champs."})

    if not RE_EMAIL.match(email):
        return templates.TemplateResponse(request=request, name="register.html",
                                          context={"erreur": "Adresse e-mail invalide."})

    if len(mot_de_passe) < 8:
        return templates.TemplateResponse(request=request, name="register.html",
                                          context={"erreur": "Le mot de passe doit contenir au moins 8 caracteres."})

    if mot_de_passe != confirmation:
        return templates.TemplateResponse(request=request, name="register.html",
                                          context={"erreur": "Les mots de passe ne correspondent pas."})

    user = creer_utilisateur(email, mot_de_passe)
    if not user:
        return templates.TemplateResponse(request=request, name="register.html",
                                          context={"erreur": "Un compte existe deja avec cette adresse."})

    request.session["user_id"] = user["id"]
    request.session["user_email"] = user["email"]
    request.session["user_role"] = user["role"]
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
