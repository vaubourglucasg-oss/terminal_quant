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



# Script exécuté dans la page du graphique : applique le thème sombre/clair sans régénérer le fichier.
# Le thème initial vient du hash de l'URL (/graph/XXX#dark) puis des messages envoyés par theme.js.
POST_SCRIPT = r"""
(function () {
  var PAL = {
    dark:  {fond: '#0f172a', texte: '#e2e8f0', grille: 'rgba(148,163,184,.18)', ligne: 'rgba(148,163,184,.40)',
            mm50: '#fbbf24', mm200: '#38bdf8', rsi: '#38bdf8', macd: '#38bdf8', signal: '#fbbf24',
            bande: 'rgba(148,163,184,.50)', remplissage: 'rgba(148,163,184,.10)'},
    light: {fond: '#ffffff', texte: '#14212C', grille: 'rgba(86,102,118,.15)', ligne: 'rgba(86,102,118,.40)',
            mm50: '#A87510', mm200: '#0D5B7C', rsi: '#0D5B7C', macd: '#0D5B7C', signal: '#A87510',
            bande: 'rgba(86,102,118,.35)', remplissage: 'rgba(86,102,118,.07)'}
  };
  var gd = document.querySelector('.plotly-graph-div');
  if (!gd) return;
  function themeInitial() {
    var h = (location.hash || '').replace('#', '');
    if (h === 'light' || h === 'dark') return h;
    try { return localStorage.getItem('quant_theme') === 'light' ? 'light' : 'dark'; } catch (e) { return 'dark'; }
  }
  function colorer(nom, attribut, valeur) {
    gd.data.forEach(function (trace, i) { if (trace.name === nom) Plotly.restyle(gd, attribut, valeur, [i]); });
  }
  function appliquer(t) {
    var p = PAL[t] || PAL.dark;
    document.documentElement.style.background = p.fond;
    document.body.style.background = p.fond;
    document.body.style.margin = '0';
    var lay = {paper_bgcolor: p.fond, plot_bgcolor: p.fond, 'font.color': p.texte, 'legend.font.color': p.texte};
    Object.keys(gd.layout).forEach(function (k) {
      if (/^[xy]axis\d*$/.test(k)) {
        lay[k + '.gridcolor'] = p.grille; lay[k + '.linecolor'] = p.ligne; lay[k + '.zerolinecolor'] = p.ligne;
      }
    });
    (gd.layout.shapes || []).forEach(function (_, i) { lay['shapes[' + i + '].line.color'] = p.ligne; });
    Plotly.relayout(gd, lay);
    colorer('MM50', 'line.color', p.mm50);
    colorer('MM200', 'line.color', p.mm200);
    colorer('RSI 14', 'line.color', p.rsi);
    colorer('MACD', 'line.color', p.macd);
    colorer('Signal', 'line.color', p.signal);
    colorer('Bollinger haut', 'line.color', p.bande);
    colorer('Bollinger bas', 'line.color', p.bande);
    colorer('Bollinger bas', 'fillcolor', p.remplissage);
  }
  appliquer(themeInitial());
  window.addEventListener('message', function (e) {
    if (e.origin === location.origin && e.data && e.data.type === 'quant-theme') appliquer(e.data.theme);
  });
})();
"""
HAUSSE, BAISSE = "#1FA37A", "#D4455A"      # teintes lisibles sur fond clair ET sombre


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
                                     name="Cours", increasing_line_color=HAUSSE,
                                     decreasing_line_color=BAISSE), row=1, col=1)
        for col, couleur, nom in (("MA50", "#A87510", "MM50"), ("MA200", "#0D5B7C", "MM200")):
            fig.add_trace(go.Scatter(x=d.index, y=d[col], mode="lines", line=dict(color=couleur, width=1.4),
                                     name=nom), row=1, col=1)
        fig.add_trace(go.Scatter(x=d.index, y=d["Haut"], mode="lines", line=dict(color="rgba(86,102,118,.35)", width=1),
                                 name="Bollinger haut", showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=d.index, y=d["Bas"], mode="lines", line=dict(color="rgba(86,102,118,.35)", width=1),
                                 fill="tonexty", fillcolor="rgba(86,102,118,.07)", name="Bollinger bas", showlegend=False), row=1, col=1)
        fig.add_trace(go.Bar(x=d.index, y=d["Volume"], name="Volume",
                             marker_color=[HAUSSE if cl >= op else BAISSE for cl, op in zip(d["Close"], d["Open"])]),
                      row=2, col=1)
        fig.add_trace(go.Scatter(x=d.index, y=d["RSI"], mode="lines", line=dict(color="#0D5B7C", width=1.4),
                                 name="RSI 14"), row=3, col=1)
        for niveau in (30, 70):
            fig.add_hline(y=niveau, line=dict(color="rgba(86,102,118,.5)", width=1, dash="dot"), row=3, col=1)
        fig.add_trace(go.Scatter(x=d.index, y=macd, mode="lines", line=dict(color="#0D5B7C", width=1.3), name="MACD"), row=4, col=1)
        fig.add_trace(go.Scatter(x=d.index, y=signal, mode="lines", line=dict(color="#A87510", width=1.3), name="Signal"), row=4, col=1)
        fig.add_trace(go.Bar(x=d.index, y=macd - signal, name="Histogramme",
                             marker_color=[HAUSSE if v >= 0 else BAISSE for v in (macd - signal)]), row=4, col=1)
        fig.update_layout(template="plotly_white", xaxis_rangeslider_visible=False, height=720,
                          margin=dict(l=40, r=20, t=30, b=20), legend=dict(orientation="h", y=1.04),
                          font=dict(family="IBM Plex Sans, sans-serif", size=12, color="#14212C"))
        fig.write_html(chemin, include_plotlyjs="cdn", post_script=POST_SCRIPT)
        return chemin
    except Exception:
        return None
