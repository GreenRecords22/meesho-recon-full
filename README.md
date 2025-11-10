
# Meesho Reconciliation — Full Edition (Advanced)

This repository contains a Streamlit app with advanced reconciliation features:
- Per-order reconciliation with fuzzy matching
- Bank-statement / payout-batch heuristic matching (greedy grouping)
- KPI dashboard and Profit & Loss calculator
- Presets library for common CSV layouts
- Example GitHub Actions workflow for scheduled runs (requires secrets and scripts)
- Optional simple password protection via environment variable `MEESHO_RECON_PASS`

## Quick start (local)
1. Create a Python venv and install:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   streamlit run app.py
   ```

## Deploy options
### Streamlit Cloud (recommended for simplicity)
1. Push this repo to GitHub.
2. Create an app on Streamlit Cloud and point it to the repo branch.
3. Add secrets (like `MEESHO_RECON_PASS`) in Streamlit settings if you want password protection.
4. Use Streamlit Cloud's domain, or add a CNAME entry on Hostinger to point a subdomain to Streamlit Cloud (follow Streamlit Cloud docs).

### Hostinger mapping (use Streamlit Cloud or Render to host the app)
Hostinger shared plans often do not support running Python web apps directly. Recommended approach:
1. Host the Streamlit app on Streamlit Cloud or Render.
2. In Hostinger DNS control panel, add a CNAME for `reconcile.yourdomain.com` pointing to the target service (e.g., `share.streamlit.io` or the endpoint provided by the host).
3. Wait for DNS to propagate (usually minutes to a few hours).

## Scheduled runs & email delivery
- You can use GitHub Actions (example workflow included) to run `reconcile_batch.py` daily and push artifacts to a release or storage.
- For email delivery, use an SMTP library (`smtplib`) or an external service (SendGrid/Mailgun). Never hardcode credentials; store them in GitHub Secrets or Streamlit secrets.

## Files of interest
- `app.py` — main Streamlit app
- `utils.py` — fuzzy matching and bank-statement helpers
- `presets.json` — mapping presets
- `.github/workflows/scheduled_reconcile.yml` — sample cron setup
- `reconcile_batch.py` — example batch reconcile runner
