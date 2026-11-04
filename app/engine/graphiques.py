"""Graphique technique interactif, généré À LA DEMANDE (clic sur une ligne) et non plus pour chaque
titre pendant le scan : cela évitait un second téléchargement d'historique par action."""
import os
import time
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.engine.math_models import calculer_rsi

dossier_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
dossier_graphs = os.path.join(dossier_base, "graphs")
os.makedirs(dossier_graphs, exist_ok=True)


def _fichier(ticker_symbol):
    return os.path.join(dossier_graphs, f"{ticker_symbol.replace('/', '_')}.html")


def generer_graphique(ticker_symbol, validite_secondes=6 * 3600):
    """Retourne le chemin du fichier HTML (réutilisé s'il a moins de 6 h) ou None."""
    chemin = _fichier(ticker_symbol)
    if os.path.exists(chemin) and time.time() - os.path.getmtime(chemin) < validite_secondes:
        return chemin
    try:
        df = yf.Ticker(ticker_symbol).history(period="2y")
        if df.empty:
            return None
        c = df["Close"]
        df["MA50"], df["MA200"] = c.rolling(50).mean(), c.rolling(200).mean()
        ma20, sd = c.rolling(20).mean(), c.rolling(20).std()
        df["Haut"], df["Bas"] = ma20 + 2 * sd, ma20 - 2 * sd
        macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
        signal = macd.ewm(span=9, adjust=False).mean()
        df["RSI"] = calculer_rsi(c)
        d = df.tail(252)
        macd, signal = macd.loc[d.index], signal.loc[d.index]

        fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.025,
                            row_heights=[0.5, 0.14, 0.18, 0.18])
        fig.add_trace(go.Candlestick(x=d.index, open=d["Open"], high=d["High"], low=d["Low"], close=d["Close"],
                                     name="Cours", increasing_line_color="#14795A",
                                     decreasing_line_color="#B1303E"), row=1, col=1)
        for col, couleur, nom in (("MA50", "#A87510", "MM50"), ("MA200", "#0D5B7C", "MM200")):
            fig.add_trace(go.Scatter(x=d.index, y=d[col], mode="lines", line=dict(color=couleur, width=1.4),
                                     name=nom), row=1, col=1)
        fig.add_trace(go.Scatter(x=d.index, y=d["Haut"], mode="lines", line=dict(color="rgba(86,102,118,.35)", width=1),
                                 name="Bollinger", showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=d.index, y=d["Bas"], mode="lines", line=dict(color="rgba(86,102,118,.35)", width=1),
                                 fill="tonexty", fillcolor="rgba(86,102,118,.07)", showlegend=False), row=1, col=1)
        fig.add_trace(go.Bar(x=d.index, y=d["Volume"], name="Volume",
                             marker_color=["#14795A" if cl >= op else "#B1303E" for cl, op in zip(d["Close"], d["Open"])]),
                      row=2, col=1)
        fig.add_trace(go.Scatter(x=d.index, y=d["RSI"], mode="lines", line=dict(color="#0D5B7C", width=1.4),
                                 name="RSI 14"), row=3, col=1)
        for niveau in (30, 70):
            fig.add_hline(y=niveau, line=dict(color="rgba(86,102,118,.5)", width=1, dash="dot"), row=3, col=1)
        fig.add_trace(go.Scatter(x=d.index, y=macd, mode="lines", line=dict(color="#0D5B7C", width=1.3), name="MACD"), row=4, col=1)
        fig.add_trace(go.Scatter(x=d.index, y=signal, mode="lines", line=dict(color="#A87510", width=1.3), name="Signal"), row=4, col=1)
        fig.add_trace(go.Bar(x=d.index, y=macd - signal, name="Histogramme",
                             marker_color=["#14795A" if v >= 0 else "#B1303E" for v in (macd - signal)]), row=4, col=1)
        fig.update_layout(template="plotly_white", xaxis_rangeslider_visible=False, height=720,
                          margin=dict(l=40, r=20, t=30, b=20), legend=dict(orientation="h", y=1.04),
                          font=dict(family="IBM Plex Sans, sans-serif", size=12, color="#14212C"))
        fig.write_html(chemin, include_plotlyjs="cdn")
        return chemin
    except Exception:
        return None
