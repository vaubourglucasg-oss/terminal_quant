"""Sentiment des titres d'actualité (indicatif, chargé à la demande et NON intégré au score).
TextBlob est entraîné sur de l'anglais généraliste : à lire comme un signal faible."""


def _titre(article):
    # yfinance a changé le format : {'title': ...} (ancien) ou {'content': {'title': ...}} (récent)
    if not isinstance(article, dict):
        return ""
    return article.get("title") or (article.get("content") or {}).get("title") or ""


def analyser_actualites(ticker_symbol, max_articles=8):
    import yfinance as yf
    try:
        news = yf.Ticker(ticker_symbol).news or []
    except Exception:
        news = []
    titres = [t for t in (_titre(a) for a in news[:max_articles]) if t]
    if not titres:
        return {"etiquette": "Aucune actualité", "score": None, "titres": []}
    try:
        from textblob import TextBlob
        scores = [TextBlob(t).sentiment.polarity for t in titres]
    except Exception:
        return {"etiquette": "Analyse indisponible", "score": None, "titres": titres}
    moy = sum(scores) / len(scores)
    etiquette = "Positif" if moy > 0.15 else ("Négatif" if moy < -0.15 else "Neutre")
    return {"etiquette": etiquette, "score": round(moy, 2), "titres": titres}
