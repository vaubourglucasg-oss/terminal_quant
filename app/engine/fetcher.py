import os
import sqlite3
import pickle
import time
from datetime import datetime
import pandas as pd
import yfinance as yf
import math
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.engine.math_models import (
    calculer_cagr, calculer_piotroski, analyser_sentiment_news, 
    generer_graphique_interactif, generer_graphique_prediction, dossier_graphs
)

db_cache_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "cache_bourse_v2.db")

PRIMES_RISQUE_PAYS = {
    "United States": 0.00, "Switzerland": 0.00, "Germany": 0.00, 
    "France": 0.004, "United Kingdom": 0.005, "Japan": 0.005, "China": 0.012, "India": 0.021
}

def init_cache_db():
    conn = sqlite3.connect(db_cache_path)
    conn.execute('CREATE TABLE IF NOT EXISTS cache_actions (ticker TEXT PRIMARY KEY, date TEXT, data BLOB)')
    conn.commit()
    conn.close()

def charger_du_cache(ticker, date_str):
    try:
        conn = sqlite3.connect(db_cache_path)
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM cache_actions WHERE ticker = ? AND date = ?", (ticker, date_str))
        row = cursor.fetchone()
        conn.close()
        if row: return pickle.loads(row[0])
    except: pass
    return None

def sauvegarder_dans_cache(ticker, date_str, data):
    try:
        conn = sqlite3.connect(db_cache_path)
        conn.execute('INSERT OR REPLACE INTO cache_actions (ticker, date, data) VALUES (?, ?, ?)', (ticker, date_str, pickle.dumps(data)))
        conn.commit()
        conn.close()
    except: pass

def nettoyer_vieux_cache():
    try:
        conn = sqlite3.connect(db_cache_path)
        conn.execute("DELETE FROM cache_actions WHERE date <= date('now', '-7 days')")
        conn.commit()
        conn.close()
    except: pass

init_cache_db()

def fetch_single_macro(nom, ticker):
    try:
        df = yf.Ticker(ticker).history(period="3mo")
        if not df.empty and len(df) > 10:
            prix = df['Close'].iloc[-1]
            ma = df['Close'].rolling(40).mean().iloc[-1] if len(df) >= 40 else df['Close'].mean()
            return nom, ((prix - ma) / ma) * 100
    except: pass
    return nom, 0

def analyser_tendances_macro():
    macro_map = {
        "Pétrole WTI": "CL=F", "Gaz Naturel": "NG=F", "Uranium": "URA", "Solaire": "TAN",
        "Or": "GC=F", "Argent": "SI=F", "Cuivre": "HG=F", "Acier": "SLX", "Aluminium": "JJU",
        "Blé": "KE=F", "Bois": "CUT", "Taux 10 Ans": "^TNX", "Index Dollar": "DX-Y.NYB", 
        "Fret Maritime": "BDRY", "Aéro & Défense": "ITA", "Semi-conducteurs": "^SOX", 
        "Construction": "ITB", "Biotech": "IBB", "Santé": "XLV", "Banque": "XLF", "Volatilité VIX": "^VIX"
    }
    tendances = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_single_macro, nom, tk) for nom, tk in macro_map.items()]
        for future in as_completed(futures):
            nom, val = future.result()
            tendances[nom] = val
    return tendances

def obtenir_taux_sans_risque():
    try:
        taux_actuel = yf.Ticker("^TNX").history(period="1d")['Close'].iloc[-1]
        return taux_actuel / 100.0 if not pd.isna(taux_actuel) else 0.042
    except: return 0.042

def analyser_action_complete(ticker_symbol, secteurs_cibles, taux_sans_risque_dynamique, donnees_macro):
    today_str = datetime.today().strftime('%Y-%m-%d')
    donnees_cache = charger_du_cache(ticker_symbol, today_str)
    
    if donnees_cache is not None:
        if secteurs_cibles and donnees_cache.get("Secteur") not in secteurs_cibles: return None
        return donnees_cache

    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info or {}
        sector = info.get("sector", "N/A")
        if secteurs_cibles and sector not in secteurs_cibles: return None

        current_price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        if current_price == 0:
            hist = ticker.history(period="5d")
            current_price = hist['Close'].iloc[-1] if not hist.empty else 0

        market_cap = info.get("marketCap", 0) or 0
        total_cash = info.get("totalCash", 0) or 0
        total_debt = info.get("totalDebt", 0) or 0
        net_debt = total_debt - total_cash
        ebitda = info.get("ebitda", 0) or 0
        fcf = info.get("freeCashflow", 0) or 0
        total_revenue = info.get("totalRevenue", 0) or 0
        operating_margins = info.get("operatingMargins", 0) or 0
        trailing_pe = info.get("trailingPE", 0) or 0
        dividend_yield = (info.get("dividendYield", 0) or 0) * 100
        beta = info.get("beta", 1.0) or 1.0
        current_ratio = info.get("currentRatio", 0) or 0
        roe = (info.get("returnOnEquity", 0) or 0) * 100
        book_value = info.get("bookValue", 0) or 0
        eps = info.get("trailingEps", 0) or 0

        try:
            fin = ticker.financials
            cf_stmt = ticker.cashflow
            bs = ticker.balance_sheet
        except: fin, cf_stmt, bs = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        
        cagr_rev_3y, cagr_fcf_3y = None, None
        if not fin.empty and 'Total Revenue' in fin.index:
            rev_s = fin.loc['Total Revenue'].dropna()
            if len(rev_s) >= 4: cagr_rev_3y = calculer_cagr(rev_s.iloc[3], rev_s.iloc[0], 3)

        if not cf_stmt.empty and ('Free Cash Flow' in cf_stmt.index or 'Operating Cash Flow' in cf_stmt.index):
            fcf_ligne = 'Free Cash Flow' if 'Free Cash Flow' in cf_stmt.index else 'Operating Cash Flow'
            fcf_s = cf_stmt.loc[fcf_ligne].dropna()
            if len(fcf_s) >= 4: cagr_fcf_3y = calculer_cagr(fcf_s.iloc[3], fcf_s.iloc[0], 3)

        devise_native = info.get("currency", "USD")
        
        rsi, ma50, ma200 = 50, 0, 0
        try:
            df_hist = ticker.history(period="1y")
            if not df_hist.empty and len(df_hist) > 200:
                close_prices = df_hist['Close']
                ma50 = close_prices.rolling(50).mean().iloc[-1]
                ma200 = close_prices.rolling(200).mean().iloc[-1]
                delta = close_prices.diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi_series = 100 - (100 / (1 + rs))
                if not rsi_series.empty and not pd.isna(rsi_series.iloc[-1]): rsi = rsi_series.iloc[-1]
        except: pass

        piotroski_score, piotroski_complet = calculer_piotroski(ticker)
        
        ebit = info.get("ebit") or info.get("operatingIncome") or (operating_margins * total_revenue)
        taux_imposition = 0.23 if sector != "Financial Services" else 0.15
        nopat = ebit * (1 - taux_imposition)
        
        shares = info.get("sharesOutstanding", 0) or 0
        total_equity = book_value * shares if book_value > 0 else (market_cap if market_cap > 0 else 1)
        capital_investi = total_debt + total_equity - total_cash
        if capital_investi <= 0: capital_investi = total_revenue * 0.3 if total_revenue > 0 else 1.0

        roic = (nopat / capital_investi) * 100 if capital_investi > 0 else 0.0
        
        prime_risque_marche = 0.055
        interest_expense = 0
        if not fin.empty and 'Interest Expense' in fin.index:
            try: interest_expense = abs(fin.loc['Interest Expense'].dropna().iloc[0])
            except: pass
                
        if total_debt > 0 and interest_expense > 0:
            cout_dette = max(0.02, min(0.15, interest_expense / total_debt))
        else:
            debt_ebitda = net_debt / ebitda if ebitda > 0 else 5.0
            prime_risque_dette = 0.015 if debt_ebitda < 1.5 else (0.035 if debt_ebitda < 3.0 else 0.07)
            cout_dette = taux_sans_risque_dynamique + prime_risque_dette
        
        pays_origine = info.get("country", "United States")
        prime_pays = PRIMES_RISQUE_PAYS.get(pays_origine, 0.02)
        cost_of_equity = max(0.065, taux_sans_risque_dynamique + (max(0.3, min(2.5, beta)) * prime_risque_marche) + prime_pays)
        
        valeur_totale = market_cap + total_debt
        poids_eq = market_cap / valeur_totale if valeur_totale > 0 else 1.0
        poids_dt = total_debt / valeur_totale if valeur_totale > 0 else 0.0
        wacc = (poids_eq * cost_of_equity) + (poids_dt * cout_dette * (1 - taux_imposition))
        wacc_pourcentage = wacc * 100
        spread = roic - wacc_pourcentage

        ev = market_cap + net_debt
        ev_ebitda = ev / ebitda if ebitda > 0 else 0.0
        fcf_yield = (fcf / market_cap) * 100 if market_cap > 0 else 0.0
        debt_to_equity = (total_debt / total_equity) * 100 if total_equity > 0 else "N/A"
        debt_ebitda = net_debt / ebitda if ebitda > 0 and sector != "Financial Services" else 0.0

        z_score = "N/A"
        if not bs.empty and sector not in ["Financial Services", "Real Estate"]:
            try:
                total_assets = bs.loc['Total Assets'].iloc[0] if 'Total Assets' in bs.index else 0
                total_liab = bs.loc['Total Liabilities Net Minority Interest'].iloc[0] if 'Total Liabilities Net Minority Interest' in bs.index else (bs.loc['Total Liabilities'].iloc[0] if 'Total Liabilities' in bs.index else 0)
                current_assets = bs.loc['Current Assets'].iloc[0] if 'Current Assets' in bs.index else 0
                current_liab = bs.loc['Current Liabilities'].iloc[0] if 'Current Liabilities' in bs.index else 0
                retained_earnings = bs.loc['Retained Earnings'].iloc[0] if 'Retained Earnings' in bs.index else 0
                
                if total_assets > 0:
                    a = (current_assets - current_liab) / total_assets
                    b = retained_earnings / total_assets
                    c = ebit / total_assets
                    d = market_cap / total_liab if total_liab > 0 else 0
                    e = total_revenue / total_assets
                    z_score = round((1.2 * a) + (1.4 * b) + (3.3 * c) + (0.6 * d) + (1.0 * e), 2)
            except: pass

        valeur_intrinseque, marge_securite = 0.0, 0.0
        if fcf > 0 and cost_of_equity > 0.025 and shares > 0:
            try:
                croissance_ct = min(max(cagr_fcf_3y if cagr_fcf_3y is not None else 0.05, 0.02), 0.15) 
                flux_futurs = [(fcf * (1 + croissance_ct)**i) / ((1 + cost_of_equity)**i) for i in range(1, 6)]
                fcf_projete = fcf * (1 + croissance_ct)**5
                valeur_terminale = (fcf_projete * 1.025) / (cost_of_equity - 0.025)
                valeur_intrinseque = (sum(flux_futurs) + (valeur_terminale / ((1 + cost_of_equity)**5))) / shares
                if current_price > 0 and valeur_intrinseque > 0:
                    marge_securite = ((valeur_intrinseque - current_price) / valeur_intrinseque) * 100
            except: pass

        valeur_graham, potentiel_graham = 0, 0
        if eps > 0 and book_value > 0 and sector not in ["Financial Services", "Technology"]:
            try:
                valeur_graham = math.sqrt(22.5 * eps * book_value)
                if current_price > 0: potentiel_graham = ((valeur_graham - current_price) / current_price) * 100
            except: pass

        s_valo, s_qualite, s_risque, s_croissance, s_momentum = 50, 50, 50, 50, 50

        if sector == "Financial Services":
            price_to_book = info.get("priceToBook", 0) or 0
            if 0 < trailing_pe < 10: s_valo += 30
            elif trailing_pe > 16: s_valo -= 25
            if roe > 12: s_qualite += 35
            elif roe < 5: s_qualite -= 25
            s_risque = 65
        else:
            if fcf_yield > 6.0: s_valo += 35
            elif fcf_yield < 0: s_valo -= 30
            if 0 < trailing_pe < 18: s_valo += 30
            elif trailing_pe > 28: s_valo -= 30
            if marge_securite > 20: s_valo += 15
            elif marge_securite < -20: s_valo -= 15
            if spread > 6.0: s_qualite += 30
            elif spread < 0: s_qualite -= 20
            if piotroski_complet and piotroski_score >= 6: s_qualite += 25
            elif piotroski_score <= 3: s_qualite -= 20
            if 0 < debt_ebitda < 2.0: s_risque += 35
            elif debt_ebitda > 3.5: s_risque -= 35

        if cagr_rev_3y is not None:
            if cagr_rev_3y > 0.08: s_croissance += 35
            elif cagr_rev_3y < 0: s_croissance -= 25

        if current_price > ma50: s_momentum += 25
        if current_price > ma200: s_momentum += 25

        s_valo = max(0, min(100, s_valo))
        if s_valo <= 35 or marge_securite < -25: s_qualite = min(s_qualite, 60)

        bonus_macro = 0
        details_macro = "Neutre ⚪"
        industry = info.get("industry", "")

        if donnees_macro:
            if "Gold" in industry: bonus_macro = donnees_macro.get("Or", 0) * 1.5; details_macro = "Or 📈"
            elif "Aerospace" in industry: bonus_macro = donnees_macro.get("Aéro & Défense", 0) * 1.5; details_macro = "Aéronautique 🚀"
            elif "Semiconductors" in industry: bonus_macro = donnees_macro.get("Semi-conducteurs", 0) * 1.5; details_macro = "Puces 💻"

        bonus_macro = max(-25, min(25, int(bonus_macro)))
        s_momentum = max(0, min(100, s_momentum + bonus_macro))
        s_croissance = max(0, min(100, s_croissance + (bonus_macro / 2)))

        score_combine = int((s_valo * 0.35) + (s_qualite * 0.25) + (s_croissance * 0.15) + (s_momentum * 0.15) + (s_risque * 0.10))

        recommandation = "CONSERVER"
        if score_combine >= 75 and spread >= 2 and s_risque >= 45 and s_valo >= 40: recommandation = "ACHAT FORT"
        elif score_combine >= 63 and spread >= 0 and s_risque >= 35: recommandation = "ACHAT"
        elif score_combine <= 42 or s_risque <= 25: recommandation = "VENTE"
        elif s_valo <= 25 and score_combine >= 60: recommandation = "CONSERVER (Trop chère)"

        graph_path = generer_graphique_interactif(ticker_symbol)

        resultat_dict = {
            "Ticker": ticker_symbol, "Nom": info.get("shortName", ticker_symbol), "Secteur": sector,
            "Summary": info.get("longBusinessSummary", "Aucune description."), "Yahoo_URL": f"https://finance.yahoo.com/quote/{ticker_symbol}/profile",
            "Devise Origine": devise_native, "Prix (Local)": round(current_price, 2) if current_price > 0 else "N/A",
            "Score /100": int(score_combine), "Valo /100": int(s_valo), "Qual /100": int(s_qualite),
            "Crois /100": int(s_croissance), "Risq /100": int(s_risque), "Mom /100": int(s_momentum),
            "Signal": recommandation, "ROIC (%)": round(roic, 1) if roic != 0 else "N/A",
            "Marge Opé (%)": round(operating_margins * 100, 1) if operating_margins != 0 else "N/A",
            "D/E (%)": round(debt_to_equity, 1) if isinstance(debt_to_equity, float) else "N/A",
            "Z-Score": z_score, "WACC (%)": round(wacc_pourcentage, 1) if wacc_pourcentage != 0 else "N/A",
            "Spread (%)": round(spread, 1) if spread != 0 else "N/A", "FCF Yield (%)": round(fcf_yield, 1) if fcf_yield != 0 else "N/A",
            "PER": round(trailing_pe, 1) if trailing_pe > 0 else "N/A", "EV/EBITDA": round(ev_ebitda, 1) if ev_ebitda > 0 else "N/A",
            "Piotroski": f"{piotroski_score}/9", "CAGR CA 3y (%)": round(cagr_rev_3y * 100, 1) if cagr_rev_3y is not None else "N/A",
            "CAGR FCF 3y (%)": round(cagr_fcf_3y * 100, 1) if cagr_fcf_3y is not None else "N/A",
            "Div Yield (%)": round(dividend_yield, 2) if dividend_yield > 0 else "N/A",
            "Valeur DCF": round(valeur_intrinseque, 2) if valeur_intrinseque > 0 else "N/A",
            "Marge Séc. (%)": round(marge_securite, 1) if valeur_intrinseque > 0 else "N/A",
            "Initiés": "Neutre ⚪", "Macro": details_macro, "Mise à jour": today_str, "Graph_URL": graph_path if graph_path else ""
        }
        sauvegarder_dans_cache(ticker_symbol, today_str, resultat_dict)
        return resultat_dict
    except Exception as e:
        print(f"Erreur sur {ticker_symbol} : {e}")
        return None