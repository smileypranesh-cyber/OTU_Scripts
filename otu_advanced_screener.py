#Otu advanced screener · PY
#!/usr/bin/env python3
"""
OTU Advanced Strategy Screener — Live Data Version
Screens for: Wheel (CC/CSP), Bull/Bear Spreads, Iron Condors, LEAPs, Diagonals/PMCC, Strangles, Calendars
 
Run: python3 otu_advanced_screener.py
Or:  python3 otu_advanced_screener.py --strategy leaps
Or:  python3 otu_advanced_screener.py --strategy condors
Or:  python3 otu_advanced_screener.py CRDO NEM SLB
 
Requires: pip install yfinance pandas numpy
"""
 
import os

import yfinance as yf
import pandas as pd
import numpy as np
import json
import datetime
import time
import sys
import argparse
 
# ── CONFIG ────────────────────────────────────────────────────────────────────
ACCOUNT_SIZE = 120000   # USD — update this
MIN_SCORE    = 7.0
VIX_LEVEL    = 15.73    # Update daily or set to None to skip VIX-based filtering
 
OTU_STOCKS = [
    'AMD','VRT','PLTR','SHOP','DELL','CRDO','ANET',
    'HOOD','WDC','CCJ','KTOS','FTNT','CSCO',
    'META','GOOGL','AMZN','NVDA',
    'SOFI','CDE','IREN','ADI','CCL','HL','AMAT','LRCX',
    'APH','EQT','NEM','FCX','RTX','GLW','COHR',
    'DRAM','INTC','CEG','TER','HPE','SKHY',
    'BE','KLAC','FLEX','CLS','WMT','SLB','GE',
    'FUTU','NBIS','MU'
]
 
STRATEGIES = ['wheel','spreads','condors','leaps','diagonal','strangle','calendar','all']
 
# ── COLOURS ───────────────────────────────────────────────────────────────────
class C:
    GREEN  = '\033[92m'
    YELLOW = '\033[93m'
    RED    = '\033[91m'
    BLUE   = '\033[94m'
    CYAN   = '\033[96m'
    MAGENTA= '\033[95m'
    BOLD   = '\033[1m'
    DIM    = '\033[2m'
    RESET  = '\033[0m'
 
def ok(s):   return f"{C.GREEN}{s}{C.RESET}"
def wn(s):   return f"{C.YELLOW}{s}{C.RESET}"
def bd(s):   return f"{C.RED}{s}{C.RESET}"
def bl(s):   return f"{C.BLUE}{s}{C.RESET}"
def cy(s):   return f"{C.CYAN}{s}{C.RESET}"
def mg(s):   return f"{C.MAGENTA}{s}{s}{C.RESET}"
def bo(s):   return f"{C.BOLD}{s}{C.RESET}"
def dm(s):   return f"{C.DIM}{s}{C.RESET}"
 
# ── TECHNICAL CALCULATIONS ────────────────────────────────────────────────────
def calc_rsi(closes, period=14):
    delta = closes.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return round((100 - 100 / (1 + rs)).iloc[-1], 1)
 
def calc_macd(closes):
    ema12  = closes.ewm(span=12).mean()
    ema26  = closes.ewm(span=26).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    hist   = macd - signal
    return macd.iloc[-1] > signal.iloc[-1], hist.iloc[-1]
 
def calc_bb(closes, period=20):
    sma   = closes.rolling(period).mean()
    std   = closes.rolling(period).std()
    upper = (sma + 2*std).iloc[-1]
    lower = (sma - 2*std).iloc[-1]
    mid   = sma.iloc[-1]
    price = closes.iloc[-1]
    pct_b = (price - lower) / (upper - lower) if upper != lower else 0.5
    return {
        'at_lower': price <= lower * 1.02,
        'at_upper': price >= upper * 0.98,
        'at_mid':   0.4 <= pct_b <= 0.6,
        'lower': round(lower, 2),
        'mid':   round(mid, 2),
        'upper': round(upper, 2),
        'pct_b': round(pct_b, 2),
        'width': round((upper - lower) / mid * 100, 1)
    }
 
def calc_ma(closes):
    ma200 = closes.rolling(200).mean().iloc[-1] if len(closes) >= 200 else closes.mean()
    ma50  = closes.rolling(50).mean().iloc[-1]  if len(closes) >= 50  else closes.mean()
    ma20  = closes.rolling(20).mean().iloc[-1]
    return round(ma200, 2), round(ma50, 2), round(ma20, 2)
 
def calc_iv(ticker_obj):
    """Get IV from nearest options expiry"""
    try:
        exps = ticker_obj.options
        if not exps: return None
        chain = ticker_obj.option_chain(exps[0])
        puts  = chain.puts
        if puts.empty: return None
        iv = puts['impliedVolatility'].dropna().mean() * 100
        return round(iv, 1)
    except:
        return None
 
def get_earnings(ticker_obj):
    try:
        cal = ticker_obj.calendar
        if cal is not None and not cal.empty:
            earn_date = cal.iloc[0, 0]
            if hasattr(earn_date, 'date'): earn_date = earn_date.date()
            days = (earn_date - datetime.date.today()).days
            return earn_date.strftime('%b %d'), days
    except:
        pass
    return 'Unknown', 999
 
def get_options_chain(ticker_obj, price, min_dte=14, max_dte=45):
    """Get best expiry and chain within DTE range"""
    try:
        exps = ticker_obj.options
        if not exps: return None, None, None
 
        now = datetime.datetime.now()
        target_exp = None
        target_dte = None
 
        for exp in exps:
            exp_dt = datetime.datetime.strptime(exp, '%Y-%m-%d')
            dte = (exp_dt - now).days
            if min_dte <= dte <= max_dte:
                target_exp = exp
                target_dte = dte
                break
 
        if not target_exp and exps:
            exp_dt = datetime.datetime.strptime(exps[0], '%Y-%m-%d')
            target_exp = exps[0]
            target_dte = (exp_dt - now).days
 
        if not target_exp: return None, None, None
 
        chain = ticker_obj.option_chain(target_exp)
        exp_label = datetime.datetime.strptime(target_exp, '%Y-%m-%d').strftime('%b %d')
        return chain, exp_label, target_dte
 
    except:
        return None, None, None
 
def get_leap_chain(ticker_obj, price):
    """Get LEAP expiry 300-500 days out"""
    try:
        exps = ticker_obj.options
        if not exps: return None, None, None
 
        now = datetime.datetime.now()
        for exp in exps:
            exp_dt = datetime.datetime.strptime(exp, '%Y-%m-%d')
            dte = (exp_dt - now).days
            if 300 <= dte <= 550:
                chain = ticker_obj.option_chain(exp)
                exp_label = exp_dt.strftime('%b %Y')
                return chain, exp_label, dte
 
        return None, None, None
    except:
        return None, None, None
 
# ── STRATEGY SCORERS ─────────────────────────────────────────────────────────
 
def score_wheel(data):
    """CC / CSP wheel strategy"""
    score = 0.0
    notes = []
    recs  = []
 
    p = data['price']
    iv = data['iv'] or 30
    rsi = data['rsi']
    bb = data['bb']
    macd_bull = data['macd_bull']
    above_200 = data['above_200ma']
    earnings_days = data['earnings_days']
    chain = data['chain']
    exp_label = data['exp_label']
    dte = data['dte']
    max_pos = ACCOUNT_SIZE * 0.10
 
    # Hard rules
    if not above_200: score = min(score, 5.0); notes.append('Below 200MA')
    else: score += 2.5; notes.append('Above 200MA ✓')
 
    if earnings_days < 30: score = min(score, 5.0); notes.append(f'Earnings {data["earnings_date"]} inside window')
    else: score += 1.0; notes.append(f'Earnings {data["earnings_date"]} clear ✓')
 
    if macd_bull: score += 0.5
    if rsi < 35: score += 0.5; notes.append('RSI oversold — CSP entry ✓')
    if iv > 40: score += 0.5
    if iv > 70: score += 0.3
 
    # Find best CSP
    best_csp = None
    if chain:
        puts = chain.puts
        puts = puts[(puts['strike'] < p * 0.97) & (puts['strike'] > p * 0.85) & (puts['bid'] > 0.05)]
        if not puts.empty:
            puts = puts.copy()
            puts['otm'] = (p - puts['strike']) / p
            puts['d_proxy'] = 0.5 - puts['otm'] * 2
            t = puts.iloc[(puts['d_proxy'] - 0.23).abs().argsort()[:1]]
            if not t.empty:
                r = t.iloc[0]
                roi = (r['bid'] / r['strike']) * 100
                fits = r['strike'] * 100 <= max_pos
                if roi >= 1.5: score += 1.5
                if fits: score += 0.5
                best_csp = {
                    'type': 'CSP',
                    'strike': r['strike'],
                    'bid': round(r['bid'], 2),
                    'roi': round(roi, 2),
                    'delta': round(abs(r.get('delta', 0.23)), 2),
                    'collateral': round(r['strike'] * 100, 0),
                    'fits': fits,
                    'exp': exp_label,
                    'dte': dte
                }
                recs.append(best_csp)
 
    # Find best CC
    best_cc = None
    if chain:
        calls = chain.calls
        calls = calls[(calls['strike'] > p * 1.03) & (calls['strike'] < p * 1.15) & (calls['bid'] > 0.05)]
        if not calls.empty:
            calls = calls.copy()
            calls['otm'] = (calls['strike'] - p) / p
            calls['d_proxy'] = 0.5 - calls['otm'] * 2
            t = calls.iloc[(calls['d_proxy'] - 0.27).abs().argsort()[:1]]
            if not t.empty:
                r = t.iloc[0]
                roi = (r['bid'] / p) * 100
                fits = p * 100 <= max_pos
                if roi >= 1.5 and not best_csp: score += 1.0
                best_cc = {
                    'type': 'CC',
                    'strike': r['strike'],
                    'bid': round(r['bid'], 2),
                    'roi': round(roi, 2),
                    'delta': round(r.get('delta', 0.27), 2),
                    'collateral': round(p * 100, 0),
                    'fits': fits,
                    'exp': exp_label,
                    'dte': dte
                }
                if not best_csp: recs.append(best_cc)
 
    score = round(min(10.0, max(0.0, score)), 1)
    return {'strategy': 'Wheel (CC/CSP)', 'score': score, 'recs': recs, 'notes': notes}
 
 
def score_spreads(data):
    """Bull call spread / Bear put spread"""
    score = 0.0
    notes = []
    recs  = []
 
    p = data['price']
    iv = data['iv'] or 30
    rsi = data['rsi']
    bb = data['bb']
    macd_bull = data['macd_bull']
    above_200 = data['above_200ma']
    earnings_days = data['earnings_days']
    chain = data['chain']
    exp_label = data['exp_label']
    dte = data['dte']
 
    if earnings_days < 30: score = min(score, 4.0); notes.append(f'Earnings {data["earnings_date"]} inside window')
    else: score += 1.0
 
    # Bull call spread — bullish setup
    bull_setup = above_200 and macd_bull and rsi < 65 and rsi > 35
    # Bear put spread — bearish setup
    bear_setup = rsi > 70 or (not above_200 and rsi > 60)
 
    if bull_setup:
        score += 2.0
        notes.append('Bullish setup — bull call spread candidate')
        if iv < 50: score += 1.0; notes.append('Low IV — buying spreads efficient ✓')
        if bb['at_lower']: score += 1.0; notes.append('At lower BB — ideal bull spread entry ✓')
        if macd_bull: score += 0.5
 
        # Find bull call spread
        if chain:
            calls = chain.calls
            atm_calls = calls[(calls['strike'] >= p * 0.98) & (calls['strike'] <= p * 1.05) & (calls['bid'] > 0)]
            otm_calls = calls[(calls['strike'] > p * 1.05) & (calls['strike'] <= p * 1.20) & (calls['bid'] > 0)]
 
            if not atm_calls.empty and not otm_calls.empty:
                long_call = atm_calls.iloc[(atm_calls['strike'] - p).abs().argsort()[:1]].iloc[0]
                short_call = otm_calls.iloc[0]
 
                debit = round(long_call['ask'] - short_call['bid'], 2)
                width = round(short_call['strike'] - long_call['strike'], 2)
                max_profit = round(width - debit, 2)
                ratio = round(max_profit / debit, 2) if debit > 0 else 0
                breakeven = round(long_call['strike'] + debit, 2)
 
                if ratio >= 1.5: score += 1.5; notes.append(f'Ratio {ratio}:1 ✓')
                elif ratio >= 1.0: score += 0.5
 
                recs.append({
                    'type': 'Bull Call Spread',
                    'long_strike': long_call['strike'],
                    'short_strike': short_call['strike'],
                    'debit': debit,
                    'max_profit': max_profit,
                    'ratio': ratio,
                    'breakeven': breakeven,
                    'exp': exp_label,
                    'dte': dte
                })
 
    elif bear_setup:
        score += 1.5
        notes.append('Bearish setup — bear put spread candidate')
        if iv < 50: score += 0.5; notes.append('Low IV — buying puts efficient')
        if rsi > 75: score += 1.0; notes.append(f'RSI {rsi} — extremely overbought ✓')
 
        if chain:
            puts = chain.puts
            atm_puts = puts[(puts['strike'] >= p * 0.95) & (puts['strike'] <= p * 1.02) & (puts['bid'] > 0)]
            otm_puts = puts[(puts['strike'] < p * 0.95) & (puts['strike'] >= p * 0.85) & (puts['bid'] > 0)]
 
            if not atm_puts.empty and not otm_puts.empty:
                long_put  = atm_puts.iloc[(atm_puts['strike'] - p).abs().argsort()[:1]].iloc[0]
                short_put = otm_puts.iloc[-1]
 
                debit = round(long_put['ask'] - short_put['bid'], 2)
                width = round(long_put['strike'] - short_put['strike'], 2)
                max_profit = round(width - debit, 2)
                ratio = round(max_profit / debit, 2) if debit > 0 else 0
                breakeven = round(long_put['strike'] - debit, 2)
 
                if ratio >= 1.5: score += 1.5
                recs.append({
                    'type': 'Bear Put Spread',
                    'long_strike': long_put['strike'],
                    'short_strike': short_put['strike'],
                    'debit': debit,
                    'max_profit': max_profit,
                    'ratio': ratio,
                    'breakeven': breakeven,
                    'exp': exp_label,
                    'dte': dte
                })
    else:
        notes.append('No clear directional bias for spread')
 
    score = round(min(10.0, max(0.0, score)), 1)
    return {'strategy': 'Spreads', 'score': score, 'recs': recs, 'notes': notes}
 
 
def score_condor(data):
    """Iron condor — neutral high IV"""
    score = 0.0
    notes = []
    recs  = []
 
    p = data['price']
    iv = data['iv'] or 30
    rsi = data['rsi']
    bb = data['bb']
    macd_bull = data['macd_bull']
    earnings_days = data['earnings_days']
    chain = data['chain']
    exp_label = data['exp_label']
    dte = data['dte']
 
    if earnings_days < 30: return {'strategy': 'Iron Condor', 'score': 2.0, 'recs': [], 'notes': [f'Earnings {data["earnings_date"]} — skip']}
 
    # Iron condor needs: high IV + neutral price action + tight BB
    neutral = 40 <= rsi <= 65
    high_iv  = iv >= 40
    bb_tight = bb['width'] < 15
 
    if high_iv:   score += 2.5; notes.append(f'IV {iv}% elevated ✓')
    else:         notes.append(f'IV {iv}% low — condors need high IV')
 
    if neutral:   score += 2.0; notes.append(f'RSI {rsi} neutral ✓')
    else:         notes.append(f'RSI {rsi} — directional bias, condor risky')
 
    if bb_tight:  score += 1.0; notes.append('BB tight — range-bound ✓')
 
    score += 1.0  # Base for earnings clear
 
    if chain:
        calls = chain.calls
        puts  = chain.puts
 
        # Short strikes at 16-20 delta (~1 SD)
        otm_calls = calls[(calls['strike'] > p * 1.05) & (calls['strike'] < p * 1.20) & (calls['bid'] > 0)]
        otm_puts  = puts[(puts['strike'] < p * 0.95) & (puts['strike'] > p * 0.80) & (puts['bid'] > 0)]
 
        if not otm_calls.empty and not otm_puts.empty:
            short_call = otm_calls.iloc[0]
            short_put  = otm_puts.iloc[-1]
 
            # Wing strikes 5 points wide
            long_call_strike = short_call['strike'] + 5
            long_put_strike  = short_put['strike'] - 5
 
            long_calls = calls[calls['strike'] == long_call_strike]
            long_puts  = puts[puts['strike'] == long_put_strike]
 
            if long_calls.empty:
                long_call_strike = short_call['strike'] + (calls['strike'].diff().median() or 5)
                long_calls = calls[abs(calls['strike'] - long_call_strike) < 3]
 
            if long_puts.empty:
                long_put_strike = short_put['strike'] - (puts['strike'].diff().median() or 5)
                long_puts = puts[abs(puts['strike'] - long_put_strike) < 3]
 
            if not long_calls.empty and not long_puts.empty:
                call_credit = round(short_call['bid'] - long_calls.iloc[0]['ask'], 2)
                put_credit  = round(short_put['bid'] - long_puts.iloc[0]['ask'], 2)
                total_credit = round(call_credit + put_credit, 2)
                wing_width = 5
                max_loss = round(wing_width - total_credit, 2)
                ror = round(total_credit / max_loss * 100, 1) if max_loss > 0 else 0
 
                if total_credit > 0: score += 1.5
                if ror >= 25: score += 0.5; notes.append(f'ROR {ror}% ✓')
 
                recs.append({
                    'type': 'Iron Condor',
                    'short_call': short_call['strike'],
                    'long_call': round(long_call_strike, 2),
                    'short_put': short_put['strike'],
                    'long_put': round(long_put_strike, 2),
                    'credit': total_credit,
                    'max_loss': max_loss,
                    'ror': ror,
                    'exp': exp_label,
                    'dte': dte
                })
 
    score = round(min(10.0, max(0.0, score)), 1)
    return {'strategy': 'Iron Condor', 'score': score, 'recs': recs, 'notes': notes}
 
 
def score_leaps(data):
    """LEAPS long call — 365+ DTE bullish"""
    score = 0.0
    notes = []
    recs  = []
 
    p = data['price']
    iv = data['iv'] or 30
    rsi = data['rsi']
    bb = data['bb']
    above_200 = data['above_200ma']
    ma200 = data['ma200']
    leap_chain = data.get('leap_chain')
    leap_exp = data.get('leap_exp')
    leap_dte = data.get('leap_dte')
    max_pos = ACCOUNT_SIZE * 0.10
 
    if not above_200: score = min(score, 5.0); notes.append('Below 200MA — max 5.0')
    else: score += 2.5; notes.append('Above 200MA ✓')
 
    # Lower BB = ideal LEAP entry
    if bb['at_lower']: score += 2.0; notes.append('At lower BB — ideal LEAP entry ✓')
    elif bb['pct_b'] < 0.35: score += 1.0; notes.append('Near lower BB ✓')
 
    if rsi < 40: score += 1.0; notes.append(f'RSI {rsi} oversold — good entry ✓')
    elif rsi < 50: score += 0.5
 
    pct_above_200 = ((p - ma200) / ma200) * 100
    if pct_above_200 < 30: score += 0.5; notes.append(f'{pct_above_200:.1f}% above 200MA — not overextended ✓')
 
    if leap_chain:
        calls = leap_chain.calls
        # Target delta 0.65-0.75 deep ITM
        itm_calls = calls[(calls['strike'] < p * 0.95) & (calls['ask'] > 0) & (calls['ask'] < max_pos/100)]
        if not itm_calls.empty:
            t = itm_calls.iloc[(itm_calls['strike'] - p * 0.88).abs().argsort()[:1]]
            if not t.empty:
                r = t.iloc[0]
                gtc = round(r['ask'] * 1.10, 2)
                fits = r['ask'] * 100 <= max_pos
                if fits: score += 1.5; notes.append('LEAP fits 10% rule ✓')
                else: notes.append(f'LEAP cost ${r["ask"]*100:,.0f} — oversized for account')
 
                recs.append({
                    'type': 'LEAP Long Call',
                    'strike': r['strike'],
                    'ask': round(r['ask'], 2),
                    'cost': round(r['ask'] * 100, 0),
                    'delta': round(r.get('delta', 0.70), 2),
                    'breakeven': round(r['strike'] + r['ask'], 2),
                    'gtc_target': gtc,
                    'fits': fits,
                    'exp': leap_exp,
                    'dte': leap_dte
                })
 
    score = round(min(10.0, max(0.0, score)), 1)
    return {'strategy': 'LEAP', 'score': score, 'recs': recs, 'notes': notes}
 
 
def score_diagonal(data):
    """Poor Man's Covered Call (PMCC) — diagonal spread"""
    score = 0.0
    notes = []
    recs  = []
 
    p = data['price']
    iv = data['iv'] or 30
    rsi = data['rsi']
    above_200 = data['above_200ma']
    bb = data['bb']
    leap_chain = data.get('leap_chain')
    leap_exp = data.get('leap_exp')
    leap_dte = data.get('leap_dte')
    chain = data['chain']
    exp_label = data['exp_label']
    dte = data['dte']
    max_pos = ACCOUNT_SIZE * 0.10
 
    if not above_200: score = min(score, 5.0); notes.append('Below 200MA')
    else: score += 2.0; notes.append('Above 200MA ✓')
 
    if iv >= 30 and iv <= 60: score += 1.5; notes.append(f'IV {iv}% moderate — good for PMCC ✓')
    elif iv > 60: notes.append(f'IV {iv}% high — PMCC works but LEAP expensive')
    else: notes.append(f'IV {iv}% low — PMCC less efficient')
 
    if bb['at_lower']: score += 1.0; notes.append('Lower BB — good LEAP entry timing ✓')
 
    long_leg = None
    short_leg = None
 
    # Long leg — LEAP delta 0.70
    if leap_chain:
        calls = leap_chain.calls
        itm = calls[(calls['strike'] < p * 0.95) & (calls['ask'] > 0) & (calls['ask'] * 100 <= max_pos)]
        if not itm.empty:
            t = itm.iloc[(itm['strike'] - p * 0.88).abs().argsort()[:1]]
            if not t.empty:
                r = t.iloc[0]
                long_leg = {
                    'strike': r['strike'],
                    'ask': round(r['ask'], 2),
                    'cost': round(r['ask'] * 100, 0),
                    'exp': leap_exp,
                    'dte': leap_dte
                }
                score += 1.0
 
    # Short leg — near-term OTM call delta 0.25-0.30
    if chain:
        calls = chain.calls
        otm = calls[(calls['strike'] > p * 1.03) & (calls['strike'] < p * 1.12) & (calls['bid'] > 0)]
        if not otm.empty:
            otm = otm.copy()
            otm['d_proxy'] = 0.5 - (otm['strike'] - p) / p * 2
            t = otm.iloc[(otm['d_proxy'] - 0.27).abs().argsort()[:1]]
            if not t.empty:
                r = t.iloc[0]
                short_leg = {
                    'strike': r['strike'],
                    'bid': round(r['bid'], 2),
                    'roi_on_leap': None,
                    'exp': exp_label,
                    'dte': dte
                }
                if long_leg:
                    months_to_recover = round(long_leg['cost'] / (r['bid'] * 100), 1)
                    short_leg['months_to_recover'] = months_to_recover
                    score += 1.5
                    notes.append(f'LEAP paid off in ~{months_to_recover} months of CCs ✓')
 
    if long_leg and short_leg:
        net_debit = round(long_leg['ask'] - short_leg['bid'], 2)
        recs.append({
            'type': 'PMCC (Diagonal)',
            'long_strike': long_leg['strike'],
            'long_exp': long_leg['exp'],
            'long_cost': long_leg['ask'],
            'short_strike': short_leg['strike'],
            'short_exp': short_leg['exp'],
            'short_credit': short_leg['bid'],
            'net_debit': net_debit,
            'months_to_recover': short_leg.get('months_to_recover'),
            'dte_short': dte
        })
 
    score = round(min(10.0, max(0.0, score)), 1)
    return {'strategy': 'PMCC/Diagonal', 'score': score, 'recs': recs, 'notes': notes}
 
 
def score_strangle(data):
    """Short strangle — very high IV neutral"""
    score = 0.0
    notes = []
    recs  = []
 
    p = data['price']
    iv = data['iv'] or 30
    rsi = data['rsi']
    earnings_days = data['earnings_days']
    chain = data['chain']
    exp_label = data['exp_label']
    dte = data['dte']
    bb = data['bb']
 
    if earnings_days < 30:
        notes.append(f'Earnings {data["earnings_date"]} — skip strangle')
        return {'strategy': 'Strangle', 'score': 2.0, 'recs': [], 'notes': notes}
 
    if iv >= 60:   score += 3.0; notes.append(f'IV {iv}% — excellent for strangle ✓')
    elif iv >= 45: score += 1.5; notes.append(f'IV {iv}% — acceptable')
    else:          notes.append(f'IV {iv}% too low for strangle'); return {'strategy': 'Strangle', 'score': 2.0, 'recs': [], 'notes': notes}
 
    neutral = 35 <= rsi <= 65
    if neutral: score += 1.5; notes.append(f'RSI {rsi} neutral ✓')
    else: notes.append(f'RSI {rsi} — directional bias')
 
    score += 1.0  # earnings clear
 
    if chain:
        calls = chain.calls
        puts  = chain.puts
 
        # 16 delta wings
        otm_calls = calls[(calls['strike'] > p * 1.05) & (calls['bid'] > 0)]
        otm_puts  = puts[(puts['strike'] < p * 0.95) & (puts['bid'] > 0)]
 
        if not otm_calls.empty and not otm_puts.empty:
            sc = otm_calls.iloc[0]
            sp = otm_puts.iloc[-1]
 
            total_credit = round(sc['bid'] + sp['bid'], 2)
            be_upper = round(sc['strike'] + total_credit, 2)
            be_lower = round(sp['strike'] - total_credit, 2)
            width    = round(sc['strike'] - sp['strike'], 2)
 
            if total_credit > 0: score += 1.5
            notes.append(f'Profit zone: ${be_lower} — ${be_upper}')
 
            recs.append({
                'type': 'Short Strangle',
                'short_call': sc['strike'],
                'short_put': sp['strike'],
                'call_credit': round(sc['bid'], 2),
                'put_credit': round(sp['bid'], 2),
                'total_credit': total_credit,
                'be_upper': be_upper,
                'be_lower': be_lower,
                'width': width,
                'exp': exp_label,
                'dte': dte
            })
 
    score = round(min(10.0, max(0.0, score)), 1)
    return {'strategy': 'Strangle', 'score': score, 'recs': recs, 'notes': notes}
 
 
def score_calendar(data):
    """Calendar spread — low IV, neutral"""
    score = 0.0
    notes = []
    recs  = []
 
    p = data['price']
    iv = data['iv'] or 30
    rsi = data['rsi']
    bb = data['bb']
    earnings_days = data['earnings_days']
    chain = data['chain']
    exp_label = data['exp_label']
    dte = data['dte']
 
    # Calendar needs LOW IV to buy and stock near ATM
    if iv <= 30:   score += 3.0; notes.append(f'IV {iv}% low — great for calendar ✓')
    elif iv <= 45: score += 1.5; notes.append(f'IV {iv}% moderate — acceptable')
    else:          notes.append(f'IV {iv}% high — calendars expensive'); return {'strategy': 'Calendar', 'score': 2.0, 'recs': [], 'notes': notes}
 
    neutral = 40 <= rsi <= 60
    if neutral: score += 2.0; notes.append(f'RSI {rsi} neutral — ideal ✓')
 
    near_atm = abs(p - bb['mid']) / p < 0.05
    if near_atm: score += 1.5; notes.append('Price near 20MA — calendar sweet spot ✓')
 
    if earnings_days > 14 and earnings_days < 45:
        score += 1.0; notes.append(f'Earnings {data["earnings_date"]} — IV expansion catalyst ✓')
    elif earnings_days < 14:
        notes.append('Earnings too close')
 
    if chain:
        calls = chain.calls
        atm = calls[(calls['strike'] >= p * 0.98) & (calls['strike'] <= p * 1.02) & (calls['bid'] > 0)]
        if not atm.empty:
            short_call = atm.iloc[(atm['strike'] - p).abs().argsort()[:1]].iloc[0]
            recs.append({
                'type': 'Calendar Spread',
                'strike': short_call['strike'],
                'short_exp': exp_label,
                'short_credit': round(short_call['bid'], 2),
                'note': 'Buy back-month same strike, sell front-month',
                'dte': dte
            })
            score += 1.0
 
    score = round(min(10.0, max(0.0, score)), 1)
    return {'strategy': 'Calendar', 'score': score, 'recs': recs, 'notes': notes}
 
 
# ── MAIN DATA FETCH ───────────────────────────────────────────────────────────
def fetch_stock_data(ticker):
    """Fetch all data needed for strategy scoring"""
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period='1y')
        if hist.empty or len(hist) < 50: return None
 
        closes = hist['Close']
        price  = round(closes.iloc[-1], 2)
        prev   = closes.iloc[-2]
        change = round(((price - prev) / prev) * 100, 2)
 
        ma200, ma50, ma20 = calc_ma(closes)
        rsi  = calc_rsi(closes)
        macd_bull, macd_hist = calc_macd(closes)
        bb   = calc_bb(closes)
        iv   = calc_iv(t)
        earnings_date, earnings_days = get_earnings(t)
        chain, exp_label, dte = get_options_chain(t, price)
        leap_chain, leap_exp, leap_dte = get_leap_chain(t, price)
 
        try:
            info = t.fast_info
            name = getattr(info, 'display_name', ticker) or ticker
        except:
            name = ticker
 
        return {
            'ticker': ticker,
            'name': name,
            'price': price,
            'change': change,
            'ma200': ma200,
            'ma50': ma50,
            'ma20': ma20,
            'above_200ma': price > ma200,
            'above_50ma':  price > ma50,
            'golden_cross': ma50 > ma200,
            'rsi': rsi,
            'macd_bull': macd_bull,
            'macd_hist': round(macd_hist, 4),
            'bb': bb,
            'iv': iv,
            'earnings_date': earnings_date,
            'earnings_days': earnings_days,
            'chain': chain,
            'exp_label': exp_label,
            'dte': dte,
            'leap_chain': leap_chain,
            'leap_exp': leap_exp,
            'leap_dte': leap_dte,
        }
    except Exception as e:
        return None
 
 
# ── DISPLAY ───────────────────────────────────────────────────────────────────
def print_rec(rec, price):
    t = rec.get('type','')
 
    if t in ('CSP','CC'):
        fit = ok('✓ fits') if rec.get('fits') else wn('⚠ oversized')
        print(f"    ▸ {bo(t)} ${rec['strike']} exp {rec['exp']} ({rec['dte']}d)  bid ${rec['bid']}  ROI {rec['roi']}%  δ{rec['delta']}  collateral ${rec['collateral']:,.0f}  {fit}")
 
    elif t == 'Bull Call Spread':
        print(f"    ▸ {bo('Bull Call')} Buy ${rec['long_strike']}C / Sell ${rec['short_strike']}C  exp {rec['exp']} ({rec['dte']}d)")
        print(f"      Debit ${rec['debit']}  Max profit ${rec['max_profit']}  Ratio {rec['ratio']}:1  BE ${rec['breakeven']}")
 
    elif t == 'Bear Put Spread':
        print(f"    ▸ {bo('Bear Put')} Buy ${rec['long_strike']}P / Sell ${rec['short_strike']}P  exp {rec['exp']} ({rec['dte']}d)")
        print(f"      Debit ${rec['debit']}  Max profit ${rec['max_profit']}  Ratio {rec['ratio']}:1  BE ${rec['breakeven']}")
 
    elif t == 'Iron Condor':
        print(f"    ▸ {bo('Iron Condor')} ${rec['short_put']}P/${rec['long_put']}P — ${rec['short_call']}C/${rec['long_call']}C  exp {rec['exp']} ({rec['dte']}d)")
        print(f"      Credit ${rec['credit']}  Max loss ${rec['max_loss']}  ROR {rec['ror']}%")
 
    elif t == 'LEAP Long Call':
        fit = ok('✓ fits 10% rule') if rec.get('fits') else wn('⚠ oversized')
        print(f"    ▸ {bo('LEAP')} Buy ${rec['strike']}C  exp {rec['exp']} ({rec['dte']}d)  ask ${rec['ask']}  cost ${rec['cost']:,.0f}  δ{rec['delta']}  {fit}")
        print(f"      BE ${rec['breakeven']}  GTC sell at ${rec['gtc_target']} (+10%)")
 
    elif t == 'PMCC (Diagonal)':
        print(f"    ▸ {bo('PMCC')} Buy ${rec['long_strike']}C {rec['long_exp']} @ ${rec['long_cost']}  /  Sell ${rec['short_strike']}C {rec['short_exp']} @ ${rec['short_credit']}")
        print(f"      Net debit ${rec['net_debit']}  LEAP paid off in ~{rec.get('months_to_recover','?')} months")
 
    elif t == 'Short Strangle':
        print(f"    ▸ {bo('Strangle')} Sell ${rec['short_put']}P + ${rec['short_call']}C  exp {rec['exp']} ({rec['dte']}d)")
        print(f"      Credit ${rec['total_credit']}  Profit zone ${rec['be_lower']} — ${rec['be_upper']}")
 
    elif t == 'Calendar Spread':
        print(f"    ▸ {bo('Calendar')} ${rec['strike']} strike  Sell {rec['short_exp']} / Buy back-month")
        print(f"      Short credit ${rec['short_credit']}  {rec['note']}")
 
 
def print_stock_result(data, strategy_results):
    best = max(strategy_results, key=lambda x: x['score'])
    sc   = best['score']
 
    sc_str = f"{sc:.1f}/10"
    sc_col = ok(sc_str) if sc >= 7 else (wn(sc_str) if sc >= 6 else dm(sc_str))
 
    chg = data['change']
    chg_col = ok(f"+{chg:.2f}%") if chg >= 0 else bd(f"{chg:.2f}%")
 
    ma_col = ok('200MA✓') if data['above_200ma'] else bd('200MA✗')
    rsi_col = ok(f"RSI {data['rsi']}") if data['rsi'] < 35 else (wn(f"RSI {data['rsi']}") if data['rsi'] > 70 else f"RSI {data['rsi']}")
    iv_str  = f"IV {data['iv']:.0f}%" if data['iv'] else "IV n/a"
    earn_col = bd(f"Earn {data['earnings_date']}⚠") if data['earnings_days'] < 30 else ok(f"Earn {data['earnings_date']}✓")
 
    print(f"\n  {bo(data['ticker'])}  {sc_col}  ${data['price']}  {chg_col}  {ma_col}  {rsi_col}  {dm(iv_str)}  {earn_col}")
 
    for sr in strategy_results:
        if sr['score'] >= MIN_SCORE:
            strat_sc = ok(f"{sr['score']:.1f}") if sr['score'] >= 8 else wn(f"{sr['score']:.1f}")
            print(f"  {cy(sr['strategy'])} [{strat_sc}]")
            for rec in sr['recs']:
                print_rec(rec, data['price'])
            for note in sr['notes'][:2]:
                print(f"    {dm(note)}")
 
 
def print_summary(all_results, strategy_mode):
    passing = [(d,rs) for d,rs in all_results if any(s['score'] >= MIN_SCORE for s in rs)]
    watch   = [(d,rs) for d,rs in all_results if not any(s['score'] >= MIN_SCORE for s in rs) and any(s['score'] >= 6 for s in rs)]
 
    print(f"\n{'═'*60}")
    print(bo(f"  OTU ADVANCED SCREENER — {datetime.datetime.now().strftime('%a %b %d %Y %H:%M')}"))
    print(f"  Strategy: {strategy_mode.upper()}  |  Account: ${ACCOUNT_SIZE:,}  |  Min score: {MIN_SCORE}")
    print(f"{'═'*60}")
    print(f"  Scanned: {len(all_results)}  |  {ok(str(len(passing))+' passing')}  |  {wn(str(len(watch))+' watch')}")
    print(f"{'═'*60}")
 
    if passing:
        print(f"\n{ok('✅ PASSING ' + str(MIN_SCORE) + '/10+')}")
        for d, rs in sorted(passing, key=lambda x: max(s['score'] for s in x[1]), reverse=True):
            qualifying = [s for s in rs if s['score'] >= MIN_SCORE]
            print_stock_result(d, qualifying)
 
    if watch:
        print(f"\n{wn('👁 WATCH')}")
        for d, rs in sorted(watch, key=lambda x: max(s['score'] for s in x[1]), reverse=True):
            best = max(rs, key=lambda x: x['score'])
            print(f"  {dm(d['ticker'])}  {wn(str(best['score']))}  {dm(best['strategy'])}")
 
    print(f"\n{'═'*60}")
    print(dm("  ⚠ Always verify earnings + pull live chain in IBKR before trading"))
    print(f"{'═'*60}\n")
 
 
# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='OTU Advanced Strategy Screener')
    parser.add_argument('tickers', nargs='*', help='Tickers to scan (default: all OTU stocks)')
    parser.add_argument('--strategy', default='all', choices=STRATEGIES, help='Strategy to screen for')
    args = parser.parse_args()
 
    tickers = [t.upper() for t in args.tickers] if args.tickers else OTU_STOCKS.copy()
    strategy_mode = args.strategy
 
    print(f"\n{bo('OTU Advanced Strategy Screener — Live Data')}")
    print(f"Strategy: {strategy_mode.upper()}  |  Scanning {len(tickers)} stocks...\n")
 
    all_results = []
 
    for i, ticker in enumerate(tickers):
        pct = int((i / len(tickers)) * 40)
        bar = '█' * pct + '░' * (40 - pct)
        print(f"\r  [{bar}] {i+1}/{len(tickers)} {ticker}    ", end='', flush=True)
 
        data = fetch_stock_data(ticker)
        if not data:
            time.sleep(0.3)
            continue
 
        strategy_results = []
 
        if strategy_mode in ('wheel','all'):
            strategy_results.append(score_wheel(data))
        if strategy_mode in ('spreads','all'):
            strategy_results.append(score_spreads(data))
        if strategy_mode in ('condors','all'):
            strategy_results.append(score_condor(data))
        if strategy_mode in ('leaps','all'):
            strategy_results.append(score_leaps(data))
        if strategy_mode in ('diagonal','all'):
            strategy_results.append(score_diagonal(data))
        if strategy_mode in ('strangle','all'):
            strategy_results.append(score_strangle(data))
        if strategy_mode in ('calendar','all'):
            strategy_results.append(score_calendar(data))
 
        if strategy_results:
            all_results.append((data, strategy_results))
 
        time.sleep(0.5)
 
    print(f"\r  {'█'*40} Done!{' '*20}")
    print_summary(all_results, strategy_mode)
 
    # Save Excel
    outfile = f"otu_advanced_{strategy_mode}_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    export_rows = []
    for d, rs in all_results:
        for s in rs:
            export_rows.append({
                'ticker': d.get('ticker'),
                'price': d.get('price'),
                'change_pct': d.get('change'),
                'rsi': d.get('rsi'),
                'iv': d.get('iv'),
                'earnings_date': d.get('earnings_date'),
                'earnings_days': d.get('earnings_days'),
                'above_200ma': d.get('above_200ma'),
                'strategy': s.get('strategy'),
                'score': s.get('score'),
                'recommendations': s.get('recs'),
                'notes': s.get('notes'),
            })

    export_columns = ['ticker', 'price', 'change_pct', 'rsi', 'iv', 'earnings_date', 'earnings_days', 'above_200ma', 'strategy', 'score', 'recommendations', 'notes']
    if export_rows:
        df = pd.DataFrame(export_rows, columns=export_columns)
    else:
        df = pd.DataFrame(columns=export_columns)

    df.to_excel(outfile, index=False)

    print(f"  Results saved to {outfile}\n")
 
if __name__ == '__main__':
    main()
 