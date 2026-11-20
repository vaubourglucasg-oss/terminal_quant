"""Routes d'authentification : connexion, inscription, déconnexion.

Sessions gérées via cookie HttpOnly signé (SessionMiddleware de Starlette).
Dépendances réutilisables : get_current_user, require_admin.
"""
import re

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.engine.auth import authentifier, creer_utilisateur, get_user_by_id

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

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
    return templates.TemplateResponse(request, "login.html", {"erreur": ""})


@router.post("/login", response_class=HTMLResponse)
async def login_post(request: Request):
    form = await request.form()
    email = str(form.get("email", "")).strip()
    mot_de_passe = str(form.get("password", ""))

    if not email or not mot_de_passe:
        return templates.TemplateResponse(request, "login.html",
                                          {"erreur": "Veuillez remplir tous les champs."}, status_code=400)

    user = authentifier(email, mot_de_passe)
    if not user:
        return templates.TemplateResponse(request, "login.html",
                                          {"erreur": "Identifiants incorrects."}, status_code=401)

    request.session["user_id"] = user["id"]
    request.session["user_email"] = user["email"]
    request.session["user_role"] = user["role"]
    return RedirectResponse("/", status_code=303)


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    user = await get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "register.html", {"erreur": ""})


@router.post("/register", response_class=HTMLResponse)
async def register_post(request: Request):
    form = await request.form()
    email = str(form.get("email", "")).strip()
    mot_de_passe = str(form.get("password", ""))
    confirmation = str(form.get("password_confirm", ""))

    if not email or not mot_de_passe or not confirmation:
        return templates.TemplateResponse(request, "register.html",
                                          {"erreur": "Veuillez remplir tous les champs."}, status_code=400)

    if not RE_EMAIL.match(email):
        return templates.TemplateResponse(request, "register.html",
                                          {"erreur": "Adresse e-mail invalide."}, status_code=400)

    if len(mot_de_passe) < 8:
        return templates.TemplateResponse(request, "register.html",
                                          {"erreur": "Le mot de passe doit contenir au moins 8 caracteres."}, status_code=400)

    if mot_de_passe != confirmation:
        return templates.TemplateResponse(request, "register.html",
                                          {"erreur": "Les mots de passe ne correspondent pas."}, status_code=400)

    user = creer_utilisateur(email, mot_de_passe)
    if not user:
        return templates.TemplateResponse(request, "register.html",
                                          {"erreur": "Un compte existe deja avec cette adresse."}, status_code=409)

    request.session["user_id"] = user["id"]
    request.session["user_email"] = user["email"]
    request.session["user_role"] = user["role"]
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
