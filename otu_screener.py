#Otu screener · PY
#!/usr/bin/env python3
"""
OTU Framework Screener — Live Data Version
Run on your Mac/PC with: python3 otu_screener.py
Requires: pip install yfinance pandas numpy anthropic ta
"""
 
import yfinance as yf
import pandas as pd
import numpy as np
import json
import datetime
import time
import sys
import os
 
# ── CONFIG ────────────────────────────────────────────────────────────────────
ACCOUNT_SIZE = 100000   # USD — update this
MIN_SCORE    = 7.0
VIX_LEVEL    = None     # None = auto-fetch, or set manually e.g. 15.73
 
# All 48 OTU approved stocks
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
 
# ── COLOURS ───────────────────────────────────────────────────────────────────
class C:
    GREEN  = '\033[92m'
    YELLOW = '\033[93m'
    RED    = '\033[91m'
    BLUE   = '\033[94m'
    BOLD   = '\033[1m'
    DIM    = '\033[2m'
    RESET  = '\033[0m'
 
def ok(s):  return f"{C.GREEN}{s}{C.RESET}"
def wn(s):  return f"{C.YELLOW}{s}{C.RESET}"
def bd(s):  return f"{C.RED}{s}{C.RESET}"
def bl(s):  return f"{C.BLUE}{s}{C.RESET}"
def bo(s):  return f"{C.BOLD}{s}{C.RESET}"
def dm(s):  return f"{C.DIM}{s}{C.RESET}"
 
# ── TECHNICAL CALCULATIONS ────────────────────────────────────────────────────
def calc_rsi(closes, period=14):
    delta = closes.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).iloc[-1]
 
def calc_macd(closes):
    ema12 = closes.ewm(span=12).mean()
    ema26 = closes.ewm(span=26).mean()
    macd  = ema12 - ema26
    signal= macd.ewm(span=9).mean()
    return macd.iloc[-1] > signal.iloc[-1]  # True = bullish crossover
 
def calc_bb(closes, period=20):
    sma   = closes.rolling(period).mean()
    std   = closes.rolling(period).std()
    upper = (sma + 2*std).iloc[-1]
    lower = (sma - 2*std).iloc[-1]
    mid   = sma.iloc[-1]
    price = closes.iloc[-1]
    at_lower = price <= lower * 1.02   # within 2% of lower band
    at_upper = price >= upper * 0.98
    return at_lower, at_upper, lower, mid, upper
 
def calc_vwap(hist):
    typical = (hist['High'] + hist['Low'] + hist['Close']) / 3
    vwap    = (typical * hist['Volume']).sum() / hist['Volume'].sum()
    return hist['Close'].iloc[-1] > vwap
 
def calc_iv_rank(ticker_obj):
    """Estimate IV rank from options chain"""
    try:
        exps = ticker_obj.options
        if not exps:
            return None, None
        # Use nearest expiry
        chain = ticker_obj.option_chain(exps[0])
        puts  = chain.puts
        if puts.empty:
            return None, None
        avg_iv = puts['impliedVolatility'].dropna().mean() * 100
        # Rough IVR estimate (can't get historical IV without paid data)
        return round(avg_iv, 1), None
    except:
        return None, None
 
def find_best_options(ticker_obj, price, max_collateral, strategy='all'):
    """Find best CC and CSP from live options chain"""
    try:
        exps = ticker_obj.options
        if not exps:
            return None, None, None
 
        now = datetime.datetime.now()
        best_exp = None
        best_dte = None
 
        # Find expiry 14-40 days out
        for exp in exps:
            exp_dt = datetime.datetime.strptime(exp, '%Y-%m-%d')
            dte = (exp_dt - now).days
            if 14 <= dte <= 42:
                best_exp = exp
                best_dte = dte
                break
 
        if not best_exp:
            # Fall back to next available
            if exps:
                exp_dt = datetime.datetime.strptime(exps[0], '%Y-%m-%d')
                best_exp = exps[0]
                best_dte = (exp_dt - now).days
 
        if not best_exp:
            return None, None, None
 
        chain = ticker_obj.option_chain(best_exp)
        exp_label = datetime.datetime.strptime(best_exp, '%Y-%m-%d').strftime('%b %d')
 
        # Best CC — OTM call, delta ~0.25-0.30
        best_cc = None
        calls = chain.calls
        calls = calls[
            (calls['strike'] > price * 1.03) &
            (calls['strike'] < price * 1.15) &
            (calls['bid'] > 0.10)
        ]
        if not calls.empty:
            # Target delta ~0.27 — use OTM % as proxy
            calls = calls.copy()
            calls['otm_pct'] = (calls['strike'] - price) / price
            calls['delta_proxy'] = 0.5 - calls['otm_pct'] * 2
            # Find strike closest to 0.27 delta
            target = calls.iloc[(calls['delta_proxy'] - 0.27).abs().argsort()[:1]]
            if not target.empty:
                r = target.iloc[0]
                roi = (r['bid'] / price) * 100
                best_cc = {
                    'strike': r['strike'],
                    'bid': r['bid'],
                    'ask': r['ask'],
                    'iv': round(r['impliedVolatility'] * 100, 1),
                    'roi': round(roi, 2),
                    'delta': round(max(0.10, min(0.50, r.get('delta', 0.27))), 2),
                    'expiry': exp_label,
                    'dte': best_dte,
                    'collateral': round(price * 100, 0)
                }
 
        # Best CSP — OTM put, delta ~0.20-0.25
        best_csp = None
        puts = chain.puts
        puts = puts[
            (puts['strike'] < price * 0.97) &
            (puts['strike'] > price * 0.85) &
            (puts['bid'] > 0.10)
        ]
        if not puts.empty:
            puts = puts.copy()
            puts['otm_pct'] = (price - puts['strike']) / price
            puts['delta_proxy'] = 0.5 - puts['otm_pct'] * 2
            target = puts.iloc[(puts['delta_proxy'] - 0.23).abs().argsort()[:1]]
            if not target.empty:
                r = target.iloc[0]
                collateral = r['strike'] * 100
                roi = (r['bid'] / r['strike']) * 100
                best_csp = {
                    'strike': r['strike'],
                    'bid': r['bid'],
                    'ask': r['ask'],
                    'iv': round(r['impliedVolatility'] * 100, 1),
                    'roi': round(roi, 2),
                    'delta': round(max(0.10, min(0.50, abs(r.get('delta', 0.23)))), 2),
                    'expiry': exp_label,
                    'dte': best_dte,
                    'collateral': round(collateral, 0)
                }
 
        return best_cc, best_csp, best_dte
 
    except Exception as e:
        return None, None, None
 
# ── SCORING ───────────────────────────────────────────────────────────────────
def score_stock(ticker, account_size=120000):
    max_pos = account_size * 0.10
 
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period='1y')
 
        if hist.empty or len(hist) < 50:
            return None
 
        closes = hist['Close']
        price  = closes.iloc[-1]
        prev   = closes.iloc[-2]
        change_pct = ((price - prev) / prev) * 100
 
        # ── TECHNICAL INDICATORS ──
        ma200   = closes.rolling(200).mean().iloc[-1] if len(closes) >= 200 else closes.mean()
        ma50    = closes.rolling(50).mean().iloc[-1]  if len(closes) >= 50  else closes.mean()
        rsi     = calc_rsi(closes)
        macd_bull = calc_macd(closes)
        at_lower_bb, at_upper_bb, bb_lower, bb_mid, bb_upper = calc_bb(closes)
        above_vwap = calc_vwap(hist.tail(20))
        above_200ma = price > ma200
        above_50ma  = price > ma50
        golden_cross = ma50 > ma200
 
        # ── OPTIONS DATA ──
        best_cc, best_csp, best_dte = find_best_options(t, price, max_pos)
        iv_val, _ = calc_iv_rank(t)
 
        # ── EARNINGS ──
        try:
            cal = t.calendar
            if cal is not None and not cal.empty:
                earn_date = cal.iloc[0, 0] if hasattr(cal, 'iloc') else None
                if earn_date:
                    if hasattr(earn_date, 'date'):
                        earn_date = earn_date.date()
                    days_to_earn = (earn_date - datetime.date.today()).days
                    earnings_inside = 0 <= days_to_earn <= 35
                    earnings_label  = earn_date.strftime('%b %d')
                else:
                    earnings_inside = False
                    earnings_label  = 'Unknown'
            else:
                earnings_inside = False
                earnings_label  = 'Unknown'
        except:
            earnings_inside = False
            earnings_label  = 'Unknown'
 
        # ── SCORE ──
        score = 0.0
        reasons = []
 
        # Trend 30%
        if above_200ma:
            score += 2.5
            pct_above = ((price - ma200) / ma200) * 100
            reasons.append(f"Above 200MA by {pct_above:.1f}%")
        else:
            reasons.append("Below 200MA — max score 5.0")
            score = min(score, 5.0)
 
        if above_50ma:  score += 0.3
        if golden_cross: score += 0.3
        if above_vwap:  score += 0.4; reasons.append("Above VWAP")
 
        # Momentum 20%
        rsi_ok = 30 <= rsi <= 72
        if rsi_ok: score += 1.0
        if rsi < 35: score += 0.5; reasons.append(f"RSI oversold ({rsi:.0f}) — great CSP entry")
        elif rsi > 70: reasons.append(f"RSI overbought ({rsi:.0f})")
        if macd_bull: score += 0.5; reasons.append("MACD bullish")
        if at_lower_bb: score += 0.5; reasons.append("At lower BB — ideal entry")
 
        # Volatility 20%
        if iv_val and iv_val > 30: score += 0.5
        if iv_val and iv_val > 50: score += 0.3; reasons.append(f"High IV {iv_val:.0f}%")
 
        # Earnings hard rule
        if earnings_inside:
            reasons.append(f"⚠ Earnings {earnings_label} inside window")
            score = min(score, 5.0)
        else:
            score += 1.0
            if earnings_label != 'Unknown':
                reasons.append(f"Earnings {earnings_label} — clear")
 
        # Options setup
        best_opt = None
        strategy = 'CC'
 
        # Prefer CSP if oversold, CC if normal/overbought
        if best_csp and (rsi < 50 or not best_cc):
            best_opt = best_csp
            strategy = 'CSP'
        elif best_cc:
            best_opt = best_cc
            strategy = 'CC'
        elif best_csp:
            best_opt = best_csp
            strategy = 'CSP'
 
        if best_opt:
            roi = best_opt['roi']
            delta = best_opt['delta']
            collateral = best_opt['collateral']
            fits = collateral <= max_pos
 
            if roi >= 1.5:   score += 1.5; reasons.append(f"ROI {roi:.1f}%")
            elif roi >= 1.0: score += 0.5
            if 0.18 <= delta <= 0.38: score += 0.5
            if fits:         score += 0.5
            else:            reasons.append(f"⚠ Oversized ${collateral:,.0f} > ${max_pos:,.0f}")
            if 14 <= (best_opt.get('dte') or 0) <= 40: score += 0.3
        else:
            reasons.append("No suitable options found")
 
        # Cap and round
        score = round(min(10.0, max(0.0, score)), 1)
 
        # Action
        if score >= 7.0 and not earnings_inside:
            action = "✅ Enter — verify live chain in IBKR"
        elif score >= 6.0:
            action = "👁 Watch — check earnings calendar"
        else:
            action = "❌ Skip"
 
        return {
            'ticker':     ticker,
            'price':      round(price, 2),
            'change_pct': round(change_pct, 2),
            'score':      score,
            'strategy':   strategy,
            'above200ma': above_200ma,
            'above50ma':  above_50ma,
            'golden_cross': golden_cross,
            'above_vwap': above_vwap,
            'rsi':        round(rsi, 1),
            'macd_bull':  macd_bull,
            'at_lower_bb': at_lower_bb,
            'iv':         iv_val,
            'earnings_date':   earnings_label,
            'earnings_inside': earnings_inside,
            'best_opt':   best_opt,
            'fits_account': (best_opt['collateral'] <= max_pos) if best_opt else False,
            'reasons':    reasons,
            'action':     action,
        }
 
    except Exception as e:
        return {'ticker': ticker, 'error': str(e), 'score': 0}
 
# ── DISPLAY ───────────────────────────────────────────────────────────────────
def print_result(r):
    if 'error' in r and r['score'] == 0:
        print(f"  {bd(r['ticker'])} — {dm('error: ' + r['error'][:60])}")
        return
 
    sc   = r['score']
    tick = r['ticker']
    strat= r.get('strategy','CC')
 
    # Score colour
    sc_str = f"{sc:.1f}"
    if sc >= 8:   sc_col = ok(sc_str)
    elif sc >= 7: sc_col = wn(sc_str)
    else:         sc_col = dm(sc_str)
 
    # Price change
    chg = r.get('change_pct', 0)
    chg_str = f"({'+' if chg >= 0 else ''}{chg:.2f}%)"
    chg_col = ok(chg_str) if chg >= 0 else bd(chg_str)
 
    # Header
    print(f"\n  {bo(tick)} [{strat}]  score: {sc_col}  ${r['price']:.2f} {chg_col}")
 
    # Technicals
    ma_str  = ok("✓ Above 200MA") if r['above200ma'] else bd("✗ Below 200MA")
    rsi_val = r['rsi']
    rsi_col = ok(f"RSI {rsi_val:.0f}") if rsi_val < 40 else (wn(f"RSI {rsi_val:.0f}") if rsi_val > 65 else f"RSI {rsi_val:.0f}")
    macd_str= ok("MACD ✓") if r['macd_bull'] else bd("MACD ✗")
    bb_str  = ok("Lower BB ✓") if r['at_lower_bb'] else dm("BB mid")
    vwap_str= ok("VWAP ✓") if r['above_vwap'] else wn("VWAP ✗")
    iv_str  = f"IV {r['iv']:.0f}%" if r['iv'] else "IV n/a"
    print(f"  {ma_str}  {rsi_col}  {macd_str}  {bb_str}  {vwap_str}  {dm(iv_str)}")
 
    # Earnings
    earn_str = bd(f"⚠ Earnings {r['earnings_date']} INSIDE WINDOW") if r['earnings_inside'] else ok(f"Earnings {r['earnings_date']} — clear")
    print(f"  {earn_str}")
 
    # Best option
    opt = r.get('best_opt')
    if opt:
        fit_str = ok("✓ fits 10% rule") if r.get('fits_account') else wn("⚠ oversized")
        print(f"  ▸ {strat} ${opt['strike']:.2f} exp {opt['expiry']} ({opt['dte']}d)  bid ${opt['bid']:.2f}  ROI {opt['roi']:.1f}%  δ{opt['delta']:.2f}  IV {opt['iv']:.0f}%")
        print(f"    Collateral ${opt['collateral']:,.0f}  {fit_str}")
 
    # Action
    print(f"  {r['action']}")
 
def print_summary(results):
    passing = [r for r in results if r.get('score', 0) >= MIN_SCORE and not r.get('earnings_inside') and not r.get('error')]
    watch   = [r for r in results if 6 <= r.get('score', 0) < MIN_SCORE and not r.get('error')]
    errors  = [r for r in results if r.get('error')]
 
    print(f"\n{'═'*60}")
    print(bo(f"  OTU SCREENER RESULTS — {datetime.datetime.now().strftime('%a %b %d %Y %H:%M')}"))
    print(f"  Account: ${ACCOUNT_SIZE:,}  |  Min score: {MIN_SCORE}  |  VIX: {VIX_LEVEL or 'live'}")
    print(f"{'═'*60}")
    print(f"  Scanned: {len(results)}  |  {ok(str(len(passing))+' passing')}  |  {wn(str(len(watch))+' watch')}  |  {dm(str(len(errors))+' errors')}")
    print(f"{'═'*60}")
 
    if passing:
        print(f"\n{ok('✅ PASSING ' + str(MIN_SCORE) + '/10+ — ENTER IF CHAIN CONFIRMS')}")
        for r in sorted(passing, key=lambda x: x['score'], reverse=True):
            print_result(r)
 
    if watch:
        print(f"\n{wn('👁 WATCH — BELOW THRESHOLD OR EARNINGS RISK')}")
        for r in sorted(watch, key=lambda x: x['score'], reverse=True):
            print_result(r)
 
    skipped = [r for r in results if r.get('score', 0) < 6 and not r.get('error')]
    if skipped:
        print(f"\n{dm('❌ SKIP (' + str(len(skipped)) + ' stocks below 6/10)')}")
        tickers = ', '.join(r['ticker'] for r in sorted(skipped, key=lambda x: x['score'], reverse=True))
        print(f"  {dm(tickers)}")
 
    if errors:
        print(f"\n{bd('⚠ ERRORS (' + str(len(errors)) + ')')}")
        for r in errors:
            print(f"  {r['ticker']}: {r.get('error','')[:60]}")
 
    print(f"\n{'═'*60}")
    print(dm("  ⚠ Always verify earnings date and pull live chain in IBKR before entering any trade"))
    print(dm("  ⚠ Scores are calculated from live data but options estimates should be confirmed"))
    print(f"{'═'*60}\n")
 
# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    # Parse args
    tickers = OTU_STOCKS.copy()
    if len(sys.argv) > 1:
        tickers = [t.upper().strip() for t in ' '.join(sys.argv[1:]).split(',') if t.strip()]
 
    print(f"\n{bo('OTU Framework Screener — Live Data')}")
    print(f"Scanning {len(tickers)} stocks from Yahoo Finance...\n")
 
    results = []
    for i, ticker in enumerate(tickers):
        pct = int((i / len(tickers)) * 40)
        bar = '█' * pct + '░' * (40 - pct)
        print(f"\r  [{bar}] {i+1}/{len(tickers)} {ticker}    ", end='', flush=True)
 
        result = score_stock(ticker, ACCOUNT_SIZE)
        if result:
            results.append(result)
 
        time.sleep(0.5)  # Avoid rate limiting
 
    print(f"\r  {'█'*40} Done!{' '*20}")
 
    print_summary(results)

    # Export results to Excel using pandas
    outfile = os.path.join(os.getcwd(), f"otu_results_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")
    export_df = pd.DataFrame(results)
    if not export_df.empty:
        for col in ['best_opt', 'reasons']:
            if col in export_df.columns:
                export_df[col] = export_df[col].apply(
                    lambda v: json.dumps(v, default=str) if isinstance(v, (dict, list)) else v
                )
    export_df.to_excel(outfile, index=False)
    print(f"  Results saved to {outfile}\n")
 
if __name__ == '__main__':
    main()
 