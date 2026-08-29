# OTU_Scripts
Scripts from OTU fellow student - found this on AI Channel on 8/28/26

Jonzee78🇦🇺🏴󠁧󠁢󠁥󠁮󠁧󠁿 — 6:14 PM

🤖 This is my OTU CC and CSP screener as requested OTU Framework Screener — Built for the Community
Hey everyone! I built a Python screener that scans all 48 OTU approved stocks against Ryan's framework automatically. 

What it does:
Scans all 48 OTU stocks live from Yahoo Finance
Scores each stock against the full OTU framework (200MA, RSI, MACD, BB, VWAP, IV, Earnings)
Identifies best CC or CSP strike with ROI, delta, DTE
Flags oversized positions and earnings risks
Takes about 4 minutes to run

Setup Instructions:

Step 1 — Install Python
Download from python.org (free)

Step 2 — Install dependencies
Open Terminal (Mac) or Command Prompt (Windows) and run:
pip install yfinance pandas numpy ta

Step 3 — Download the screener
Save otu_screener.py to your Downloads folder

Step 4 — Update your account size
Open the file and change line 14:
ACCOUNT_SIZE = 120000
Replace 120000 with your account size in USD

Step 5 — Run the screener
cd ~/Downloads
python3 otu_screener.py

Results show:
✅ Passing stocks (score ≥7.0) — enter if chain confirms in IBKR
👁 Watch stocks (score 6.0-6.9)
❌ Skip stocks (below 6.0)
Important: Always verify the live chain in IBKR before entering any trade. Scores are calculated from live data but options estimates should be confirmed.
Not financial advice — always do your own research 🙏
