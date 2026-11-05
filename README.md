# ExpiryGuard

**Near-expiry stock intelligence for pharmacy chains.** ExpiryGuard predicts which medicine batches will *not* sell before they expire, then recommends the cheapest fix for each one: move it to a store that will sell it, return it to the distributor, or flag it for a markdown. It also works on the cause by capping over-ordering.

![Command Center](docs/screenshots/command_center.png)

> **All demo data is synthetic** (10 stores, 40 SKUs, ~2.5 years of simulated sales). The performance numbers below come from simulation and show that the *method* works under stated assumptions. They are **not** results from a real pharmacy chain. Run a pilot on your own data before relying on them.

---

## Why

Pharmacies lose margin to stock that expires on the shelf, often while another store a few kilometres away is running short of the same product. Chains usually handle this by gut feeling or periodic audits. ExpiryGuard replaces that with a weekly, data-driven loop:

**upload data → forecast demand → score every batch → recommend actions → approve and track them**

## What you get

| Area | Features |
|---|---|
| **Data** | Upload CSV/Excel with flexible column names, data-quality score, every cleaning action reported with counts, templates, two demo datasets |
| **Analysis** | Per store × SKU demand forecast (120 days), probabilistic expiry-risk score for every batch, mixed-integer optimiser for transfers/returns, markdown studio |
| **Decisions** | Transfer Planner (you choose the destination; every store is scored on sell-through, distance, cost), approve/reject recommendations, per-store pick-lists |
| **Workflow** | Task Board (propose → approve → dispatch → receive, with comments and history), alerts, run history with "what changed since last upload" |
| **Geography** | Map with risk bubbles, planned shipping lanes, radius search, store scorecards, editable store locations |
| **What-if** | Scenario Lab (return terms, shipping cost, risk appetite, distance limits, blocked stores), sensitivity sweeps, ROI calculator |
| **Teams** | Login, four roles, store-level restrictions, audit log, publishing an analysis for store staff |
| **Interface** | Page transitions, linked focus across pages (store/category), lasso selection, animated charts (Expiry Clock, forecast reveal, plan replay), guided workflow |
| **Reports** | Multi-sheet Excel workbook and HTML summary |

Pages: Data Hub · Command Center · Alerts · Forecast Explorer · Risk Explorer · Action Center · Transfer Planner · Task Board · Geo Map · Markdown Studio · Scenario Lab · Business Case · Run History & Reports · Model Health · Admin Console.

## Quick start

Tested on Python 3.12.

```bash
pip install -r requirements.txt
streamlit run app.py
```

1. The first launch asks you to **create the administrator account**.
2. **Data Hub → Try a demo dataset → Load demo dataset A → Run analysis** (about 15–30 s).
3. Click **Publish** so other users see the analysis, then explore the Command Center.
4. Load **demo dataset B** (30 days later), run it, and open **Run History & Reports** to see what changed between the two uploads.

User accounts, run history and published analyses are stored in `./workspace/` (override with the `EXPIRY_WORKDIR` environment variable). This folder is git-ignored; it contains password hashes.

## Using your own data

| File | Required columns | Optional |
|---|---|---|
| Sales (daily) | `date, store, sku, units` | |
| Inventory (today's stock) | `store, sku, expiry_date, quantity` | `batch_id` |
| SKU master | `sku, unit_cost` | `category, unit_price` |
| Store master | `store` | `lat, lon` (enables distance-based shipping cost and the map) |

Aliases such as `qty`, `item_code`, `branch`, `mrp`, `lot_no` are recognised. Unusable rows are dropped **and reported with counts**.
History drives the model: **12+ months** gives the ML forecast with seasonality, **45–364 days** falls back to a level + weekday model, and under 45 days is rejected. A forecast-accuracy backtest needs 18+ months.

## How it works

1. **Forecast.** Poisson gradient boosting (scikit-learn) predicts daily demand per store × SKU, directly for each of the next 120 days. Features: recent sales levels, store/SKU/category, calendar of the target day.
2. **Risk score.** Stock sells first-expiry-first-out, so a batch is at risk when demand until *its* expiry cannot cover the stock queued ahead of it. With `C` = units up to and including the batch and `D` = demand until expiry (negative binomial): `P(expires unsold) = P(D ≤ C−1)` and `E[unsold units] = Σⱼ P(D ≤ C−j)`.
3. **Optimise.** A small mixed-integer programme (SciPy/HiGHS) decides transfers and returns. Receivers may only take units they will sell with high probability, shipping has a fixed cost per lane, and returns follow distributor terms. Units with no cost-effective move are flagged for markdown review.
4. **Order cap.** Weekly orders are trimmed so stock does not exceed ~90 days of forecast demand, with a guard against stock-outs.

## Results (simulation)

All figures are from a 180-day replay of the same demand and opening stock with and without the system, on **simulated** chains (`simulator/`, `precomputed/`).

| Seed 42 | Baseline | With ExpiryGuard |
|---|---|---|
| Expiry write-offs | ₹76,163 | ₹26,454 (−65%) |
| Net contribution | ₹718,664 | ₹743,412 (+₹24,748, +3.4%) |
| Fill rate | 99.32% | 99.30% |

- **Five independent simulated chains:** write-offs fell 45–65%; net gain was positive in all five (0.4–3.4% of baseline contribution, median 1.6%). Seed 42 is the best case, so quote the range.
- **The levers are complementary, not additive:** transfers + returns alone added ₹3,582, the order cap alone ₹6,902, both together ₹24,748. Without the cap the system returns stock at a loss and the chain re-buys it.
- **Forecast:** 28-day error 32.7% vs 36.7% / 38.5% for naive baselines. It under-forecasts by about 6%.
- **Risk scores:** AUC 0.974 on 1,520 held-out batches; scores are ~14% conservative in total (4,107 expected vs 3,612 actual unsold units).

## Roles and security

| Role | Can |
|---|---|
| Administrator | Everything, including users and the audit log |
| Manager | All analysis; approves tasks |
| Analyst | Upload, analyse, publish, propose tasks (read-only on approvals) |
| Store staff | See only assigned stores; dispatch and receive their own stock |

Passwords are salted scrypt hashes; five failed sign-ins lock an account for 15 minutes; admins issue temporary passwords that must be changed at first sign-in; sign-ins, uploads, publishes, task changes and location edits are written to an audit log.
**This is application-level security, not enterprise-grade.** There is no SSO, MFA, e-mail reset or session persistence (a refresh signs you out). Data lives in one SQLite file, which suits a pilot or a single site. Serve it over HTTPS, and protect `workspace/` like a credential store (the published analysis is a pickle written only by the server).

## Project structure

```
app.py, ui.py          Streamlit shell: login gate, navigation, linked focus, theme
views/                 one module per page (+ anim.py: animated Plotly figures)
core/                  UI-independent engine (no Streamlit imports)
  io.py                ingestion + validation        forecast.py   Poisson GBM / level model
  risk.py              FEFO expiry-risk scoring      optimize.py   transfer/return MILP
  pipeline.py          forecast stage + plan stage   geo.py        distances, scorecards, transfer options
  auth.py, db.py       users, roles, audit (SQLite)  tasks.py      task workflow
  store.py, publish.py run history, published analysis   report.py  Excel / HTML reports
simulator/             synthetic chain + demo-data generator (python simulator/make_demo_data.py)
sample_data/           two demo uploads, 30 days apart
precomputed/           simulation results shown on the Business Case page
tests/                 headless end-to-end tests
prototypes/            NiceGUI and Flet front ends on the same engine
```

## Tests

```bash
python tests/test_app.py        # 56 checks: login, roles, every page, planner, tasks, geo, publish, lockout, audit
python tests/test_linking.py    # 33 checks: linked focus, selection sync, stepper/tiles, animations
```

Each takes a few minutes. Both drive the real app headlessly with Streamlit's `AppTest`, and both pass. They check logic, state and figure construction, **not appearance**. The Command Center and both prototypes were also reviewed in a real headless browser; the other pages have headless-test coverage only. Run the app and look at it.

## UI prototypes

[`prototypes/`](prototypes/README.md) contains two experimental front ends built on the same `core/` engine, to compare against Streamlit:

- **NiceGUI**: full interactive Plotly (lasso select, click-to-focus), native direction-aware slide transitions. Verified in a real browser.
- **Flet** (Flutter rendering): native animations and charts, no lasso. Partially verified.

```bash
pip install -r prototypes/requirements.txt
python prototypes/nicegui_app.py     # http://127.0.0.1:8701
python prototypes/flet_app.py        # http://127.0.0.1:8702
```

## Known limitations

- Sales are used as demand, so stock-outs hide true demand and can cause under-forecasting. Promotions, launches and prescription-pattern shifts are not modelled.
- Return terms, shipping costs and markdown response are **assumptions you set**; estimated gains are conservative per-unit lower bounds and are not comparable across risk-appetite settings.
- Distances are straight-line, not road distance. Map tiles load from the internet in the user's browser (choose the `white-bg` style offline).
- Inter-store transfers may be restricted by drug-licence, cold-chain or schedule-drug rules. Confirm with your compliance team. This is decision support, not medical or regulatory advice.
- Streamlit re-runs the script on each interaction, so transitions are CSS-based and slightly less fluid than a native front end. The click-to-select gestures on map markers could not be exercised for real.
- Not yet validated on real pharmacy data.

## Ideas / roadmap

Road-distance routing · SSO and a proper database for multi-site use · markdown elasticity learned from data · scheduled weekly runs with e-mail alerts · CI workflow running the tests · finishing the Flet prototype.

## License

No license has been chosen yet. Add one (for example MIT or Apache-2.0) before making the repository public; without a license, others have no permission to reuse the code.
