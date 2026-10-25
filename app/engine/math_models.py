import os
import math
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from textblob import TextBlob

dossier_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
dossier_graphs = os.path.join(dossier_base, "graphs")
os.makedirs(dossier_graphs, exist_ok=True)

def calculer_cagr(valeur_initiale, valeur_finale, annees):
    try:
        if pd.isna(valeur_initiale) or pd.isna(valeur_finale) or valeur_initiale <= 0 or valeur_finale <= 0 or annees <= 0:
            return 0.0
        return (valeur_finale / valeur_initiale) ** (1 / annees) - 1
    except Exception:
        return 0.0

def calculer_piotroski(ticker):
    score = 0
    criteres_valides = 0
    try:
        fin = ticker.financials
        bs = ticker.balance_sheet
        cf = ticker.cashflow
        if fin.empty or bs.empty or cf.empty:
            return 0, False
        
        net_income = fin.loc['Net Income'].iloc[0] if 'Net Income' in fin.index else None
        total_assets = bs.loc['Total Assets'].iloc[0] if 'Total Assets' in bs.index else None
        prev_total_assets = bs.loc['Total Assets'].iloc[1] if bs.shape[1] > 1 and 'Total Assets' in bs.index else None
        if net_income is not None and total_assets is not None and total_assets > 0:
            criteres_valides += 1
            if (net_income / total_assets) > 0: score += 1
            
        cfo = cf.loc['Operating Cash Flow'].iloc[0] if 'Operating Cash Flow' in cf.index else None
        if cfo is not None:
            criteres_valides += 1
            if cfo > 0: score += 1
            
        prev_net_income = fin.loc['Net Income'].iloc[1] if fin.shape[1] > 1 and 'Net Income' in fin.index else None
        if net_income is not None and prev_net_income is not None and total_assets is not None and prev_total_assets is not None and total_assets > 0 and prev_total_assets > 0:
            criteres_valides += 1
            if (net_income / total_assets) > (prev_net_income / prev_total_assets): score += 1
            
        if cfo is not None and net_income is not None:
            criteres_valides += 1
            if cfo > net_income: score += 1
            
        lt_debt = bs.loc['Long Term Debt'].iloc[0] if 'Long Term Debt' in bs.index else 0
        prev_lt_debt = bs.loc['Long Term Debt'].iloc[1] if bs.shape[1] > 1 and 'Long Term Debt' in bs.index else 0
        if total_assets is not None and prev_total_assets is not None and total_assets > 0 and prev_total_assets > 0:
            criteres_valides += 1
            leverage = lt_debt / total_assets
            prev_leverage = prev_lt_debt / prev_total_assets
            if leverage <= prev_leverage: score += 1
            
        current_assets = bs.loc['Current Assets'].iloc[0] if 'Current Assets' in bs.index else None
        current_liabilities = bs.loc['Current Liabilities'].iloc[0] if 'Current Liabilities' in bs.index else None
        prev_current_assets = bs.loc['Current Assets'].iloc[1] if bs.shape[1] > 1 and 'Current Assets' in bs.index else None
        prev_current_liabilities = bs.loc['Current Liabilities'].iloc[1] if bs.shape[1] > 1 and 'Current Liabilities' in bs.index else None
        if current_assets is not None and current_liabilities is not None and prev_current_assets is not None and prev_current_liabilities is not None and current_liabilities > 0 and prev_current_liabilities > 0:
            criteres_valides += 1
            if (current_assets / current_liabilities) >= (prev_current_assets / prev_current_liabilities): score += 1
            
        shares = fin.loc['Basic Average Shares'].iloc[0] if 'Basic Average Shares' in fin.index else None
        prev_shares = fin.loc['Basic Average Shares'].iloc[1] if fin.shape[1] > 1 and 'Basic Average Shares' in fin.index else None
        if shares is not None and prev_shares is not None:
            criteres_valides += 1
            if shares <= prev_shares: score += 1
            
        gross_profit = fin.loc['Gross Profit'].iloc[0] if 'Gross Profit' in fin.index else None
        total_revenue = fin.loc['Total Revenue'].iloc[0] if 'Total Revenue' in fin.index else None
        prev_gross_profit = fin.loc['Gross Profit'].iloc[1] if fin.shape[1] > 1 and 'Gross Profit' in fin.index else None
        prev_total_revenue = fin.loc['Total Revenue'].iloc[1] if fin.shape[1] > 1 and 'Total Revenue' in fin.index else None
        if gross_profit is not None and total_revenue is not None and prev_gross_profit is not None and prev_total_revenue is not None and total_revenue > 0 and prev_total_revenue > 0:
            criteres_valides += 1
            if (gross_profit / total_revenue) >= (prev_gross_profit / prev_total_revenue): score += 1
            
        if total_revenue is not None and prev_total_revenue is not None and total_assets is not None and prev_total_assets is not None and total_assets > 0 and prev_total_assets > 0:
            criteres_valides += 1
            if (total_revenue / total_assets) >= (prev_total_revenue / prev_total_assets): score += 1
            
    except Exception:
        pass
    
    complet = criteres_valides >= 7
    return score, complet

def analyser_sentiment_news(ticker):
    try:
        news = ticker.news
        if not news:
            return "Neutre ⚪", 0
        score_total = 0
        articles_analyses = 0
        for article in news[:5]:
            titre = article.get("title", "")
            if titre:
                analyse = TextBlob(titre)
                score_total += analyse.sentiment.polarity
                articles_analyses += 1
        if articles_analyses == 0:
            return "Neutre ⚪", 0
        score_moyen = score_total / articles_analyses
        if score_moyen > 0.15: return "Positif 🟢", 15
        elif score_moyen < -0.15: return "Négatif 🔴", -15
        else: return "Neutre ⚪", 0
    except Exception:
        return "Neutre ⚪", 0

def generer_graphique_interactif(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        df_hist = ticker.history(period="2y") 
        if df_hist.empty: return None
        df_plot = df_hist.tail(252).copy()
        
        df_plot['MA50'] = df_plot['Close'].rolling(50).mean()
        df_plot['MA200'] = df_plot['Close'].rolling(200).mean()
        df_plot['MA20'] = df_plot['Close'].rolling(20).mean()
        df_plot['StdDev'] = df_plot['Close'].rolling(20).std()
        df_plot['Upper'] = df_plot['MA20'] + (df_plot['StdDev'] * 2)
        df_plot['Lower'] = df_plot['MA20'] - (df_plot['StdDev'] * 2)

        ema12 = df_plot['Close'].ewm(span=12, adjust=False).mean()
        ema26 = df_plot['Close'].ewm(span=26, adjust=False).mean()
        df_plot['MACD'] = ema12 - ema26
        df_plot['Signal'] = df_plot['MACD'].ewm(span=9, adjust=False).mean()
        df_plot['Hist'] = df_plot['MACD'] - df_plot['Signal']

        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.6, 0.2, 0.2])

        fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name='Prix'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MA50'], mode='lines', line=dict(color='orange', width=1.5), name='MM50'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MA200'], mode='lines', line=dict(color='blue', width=1.5), name='MM200'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['Upper'], mode='lines', line=dict(color='rgba(255,255,255,0.2)', width=1), name='Bande Haute', showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['Lower'], mode='lines', line=dict(color='rgba(255,255,255,0.2)', width=1), fill='tonexty', fillcolor='rgba(255,255,255,0.05)', name='Bande Basse', showlegend=False), row=1, col=1)

        couleurs_vol = ['#34d399' if row['Close'] >= row['Open'] else '#ef4444' for _, row in df_plot.iterrows()]
        fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Volume'], marker_color=couleurs_vol, name='Volume'), row=2, col=1)

        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MACD'], mode='lines', line=dict(color='#38bdf8', width=1.5), name='MACD'), row=3, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['Signal'], mode='lines', line=dict(color='orange', width=1.5), name='Signal'), row=3, col=1)
        couleurs_macd = ['#34d399' if val >= 0 else '#ef4444' for val in df_plot['Hist']]
        fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Hist'], marker_color=couleurs_macd, name='Histogramme'), row=3, col=1)

        fig.update_layout(title=f"Analyse Technique - {ticker_symbol}", template="plotly_dark", xaxis_rangeslider_visible=False, height=650, margin=dict(l=20, r=20, t=40, b=20))
        chemin_graph = os.path.join(dossier_graphs, f"{ticker_symbol}.html")
        fig.write_html(chemin_graph, include_plotlyjs='cdn')
        return f"/graphs/{ticker_symbol}.html"
    except Exception:
        return None

def generer_graphique_prediction(ticker_symbol, score_combine=50):
    # Même structure que interactif, mais avec l'algorithme des 60 jours...
    return generer_graphique_interactif(ticker_symbol) # Raccourci temporaire si besoin, sinon colle ton code complet ici