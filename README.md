<<<<<<< HEAD
# ExpiryGuard v3 - near-expiry stock intelligence platform for pharmacy chains

A multi-page web platform. **Each cycle a user uploads fresh sales + inventory files**, the platform validates them,
forecasts demand, scores every batch for expiry risk, recommends transfers / returns / markdowns, and keeps a history so
uploads can be compared over time.

```bash
pip install -r requirements.txt
streamlit run app.py
```
First launch asks you to **create the administrator account**. Then: **Data Hub** → *Try a demo dataset* → **Run analysis** (~15-30 s) →
**Publish** so other users see it. Create users in **Admin Console**.

## What's new in v3 - an animated, linked interface (everything from v1/v2 is unchanged)
| Area | What you get |
|---|---|
| 🎞️ **Page-by-page movement** | Pages slide in **from the right when you move forward and from the left when you go back** (the direction follows the sidebar order). Cards rise in with a stagger, KPI cards lift on hover, buttons press down, the sidebar menu is a set of sliding pills, the header has a slow animated gradient. Honours the OS "reduce motion" setting |
| 🔗 **Linked focus (multi-linked options)** | One global **store + category focus** bar on every page. Set it by picking in the bar, clicking a **store bar** (Command Center, Geo scorecards, Forecast comparison), clicking a **store on the map**, choosing a **category pill**, or with "🔗 Focus on this store" buttons. Every page then follows: Command Center charts filter, Risk Explorer filters pre-fill, Forecast Explorer jumps to the store and narrows the SKU list, Geo Map highlights and re-centres the radius, Transfer Planner pre-selects the source. "Open in →" buttons carry the focus to the next page. Your manual edits on a page are never overwritten unless the focus itself changes |
| 🖱️ **Gestures** | **Lasso / box-select** bubbles in Risk Explorer - the table, KPIs and deep-dive narrow to your selection; click-to-focus on bars and map markers; hover tooltips; smooth chart transitions |
| ▶️ **Animated charts** | **Expiry Clock** (Command Center): press Play to watch expected losses accumulate over 120 days by category (its last frame equals the dashboard's total); **Forecast reveal**: the forecast bars unfold week by week; **Plan replay** (Geo Map): the shipping network builds lane by lane |
| 🧭 **Guided workflow** | A clickable stepper (Upload → Overview → Investigate → Decide → Plan → Track), Back/Next buttons on each step, and quick-action tiles on Command Center, Data Hub and Alerts |
| 🔔 **Feedback** | Toasts for key actions; celebratory balloons when a task is completed |

## What's new in v2 (all v1 features are unchanged)
| Area | Features |
|---|---|
| 🔐 **Login & roles** | Accounts stored in SQLite; passwords are salted scrypt hashes; 5 failed sign-ins lock an account for 15 min; admins issue temporary passwords that must be changed at first sign-in. Roles: **Administrator**, **Manager** (approves tasks), **Analyst** (uploads/analyses/proposes, read-only on approvals), **Store staff** (sees only assigned stores). Role-filtered navigation, store-level data restrictions, full **audit log** (sign-ins, uploads, runs, publishes, task changes, location edits) with CSV export |
| 🔀 **Transfer Planner** | *You* choose the destination. Pick a source store and batch; every other store is scored on sell-through probability, existing stock, safe capacity, distance, shipping cost and expected gain; split a batch across two stores; warnings for risky choices (blocked receiver, distance limit, over-capacity) need acknowledgement; raise the request in one click. Opens pre-filled from Action Center ("re-route") |
| 🌍 **Geo Map** | Real interactive map (bubble size = loss / loss % / high-risk batches / days of cover / stock), planned transfer lanes, radius circle, nearby-store search with distances, distance matrix, **store scorecards** (rank, cover, units in/out) and an **Edit locations** tab - saved coordinates persist across uploads and switch shipping costs to real distances |
| ✅ **Task Board** | Every approved move becomes a tracked task: Proposed → Approved → Dispatched → Completed (returns skip dispatch), with permissions per role/store, comments, history and CSV export. Duplicate active tasks are not created |
| 🔔 **Alerts** | Personal digest: tasks waiting for you, batches expiring ≤14 days and likely unsold, already-expired stock - scoped to your stores |
| 📢 **Publish** | Analysts publish an analysis; every user (incl. store staff who cannot upload) sees it automatically at sign-in |
| ⚙️ **Planning constraints** | New Scenario Lab controls: max transfer distance, stores that may not receive / may not send transfers (closed, no cold chain) |

## Pages
| Page | What the user can do |
|---|---|
| 🏠 **Data Hub** | Upload CSV/Excel (flexible column names), download templates, load demo data, see a data-quality score and every cleaning action, run the analysis |
| 📊 **Command Center** | KPI cards, alerts (expired / expiring-soon), store × category risk heatmap, risk-band donut, expiry timeline, top-10 batches |
| 🔮 **Forecast Explorer** | Pick any store × SKU: weekly history vs forecast with 80% interval, days of cover, stock-vs-demand imbalance across stores, seasonality |
| ⚠️ **Risk Explorer** | Filter by store / category / urgency / probability; bubble chart; **batch deep-dive** showing the demand distribution and per-unit sell chances |
| 🚚 **Action Center** | Approve/reject each recommendation, transfer-network map, per-store pick-lists, CSV export |
| 🏷️ **Markdown Studio** | For units that cannot be moved/returned: best discount under a user-set elasticity, batch what-ifs, portfolio table |
| 🧪 **Scenario Lab** | Change return credit, shipping cost, risk appetite; compare scenarios side by side; sensitivity sweeps; apply a profile globally |
| 💰 **Business Case** | ROI / payback calculator (low-median-high from 5 simulated chains) + simulation evidence and ablation |
| 🗂️ **Run History & Reports** | Saved runs, trend across uploads, "what changed" (cleared / still / newly high-risk), Excel + HTML reports |
| 🩺 **Model Health** | Data quality, forecast backtest vs naive baselines, risk-score calibration reference, limitations |
| 👥 **Admin Console** | Create/edit users, roles, store restrictions, reset passwords, audit log, published-analysis status |

## Upload format
| File | Required columns | Optional |
|---|---|---|
| Sales | `date, store, sku, units` | - |
| Inventory (today's stock) | `store, sku, expiry_date, quantity` | `batch_id` |
| SKU master | `sku, unit_cost` | `category, unit_price` |
| Store master | `store` | `lat, lon` (enables distance-based shipping cost) |

Aliases such as `qty`, `item_code`, `branch`, `mrp`, `lot_no` are recognised. Bad rows are dropped **and reported with counts**.
12+ months of sales gives the ML model with seasonality; 45-364 days automatically falls back to a level + weekday model; <45 days is rejected.

## Architecture
`core/io.py` ingestion + validation → `core/forecast.py` (Poisson gradient boosting, or level model) → `core/risk.py` (FEFO + negative-binomial
expiry probabilities) → `core/optimize.py` (mixed-integer programme, HiGHS) → `core/pipeline.py` (slow forecast stage is cached; fast plan stage re-runs
instantly when settings change) → `views/*` pages. `core/report.py` builds Excel/HTML; `core/store.py` persists run history to `workspace/runs/`
(override with `EXPIRY_WORKDIR`). `simulator/` regenerates demo data and holds the original validated simulation used for the Business Case evidence.

## Verification
* `python tests/test_linking.py` - **33 checks, all passing**: chart-selection sync (click, unchanged, de-select), focus pushed to widgets without overwriting user edits, category/store focus followed by Risk, Forecast, Geo and Planner pages, Clear, link buttons, stepper/Back/Next/tiles, slide direction, Expiry Clock total equals the dashboard total, plan-replay frames.
* `python tests/test_app.py` - **56 headless end-to-end checks, all passing**: first-run setup, weak-password rejection, the original 24-step journey (every v1 page and
  interaction), then the new features: planner → task creation → duplicate protection → Action Center hand-over → manager approval → map/nearby/location editing →
  new scenario constraints → user creation → admin self-demotion blocked → publish → **restricted store employee** sign-in (forced password change, sees only permitted pages
  and Store-01 data, can dispatch but not approve) → account lockout → audit-log coverage.
* With default settings the v2 optimizer gives results identical to v1 (107 / 194 / 170 units, same estimated gain on demo A); a 10 km limit or blocked receivers change the plan as expected.
* v1 checks retained: generic engine reproduces validated simulator results; messy-data cases (missing columns, bad dates, negative units, unknown SKUs, no coordinates, short history, single store).

## Known limitations (read before deploying)
* **The animations and click/lasso gestures are not visually verified.** No browser was available, so tests cover logic, state and figure construction (and CSS sanity: balanced rules, defined keyframes, matching selectors) but not how it looks or feels. Click-to-select on **map markers** and **bars** relies on Plotly/Streamlit selection events and could not be exercised for real; the focus bar, pills and buttons give an equivalent path for every link.
* Streamlit cannot run page JavaScript, so there are no count-up number animations or drag-and-drop layouts. The sidebar pill highlight uses the CSS `:has()` selector (current Chrome, Edge, Safari and Firefox 121+).
* **Not yet visually reviewed in a browser** - tested headlessly; check layout on your screens.
* **Authentication is application-level, not enterprise-grade.** Serve over HTTPS; there is no SSO, MFA, e-mail password reset or session persistence (a browser refresh signs you out).
  Data lives in one SQLite file plus a folder on one server - fine for a pilot or single-site deployment, not for high concurrency or multi-tenant use (one organisation per deployment).
* The published analysis is a pickle file written only by the server for admin/manager/analyst; protect the `workspace/` folder like any credential store.
* Map tiles load from the internet in the user's browser (choose the `white-bg` style for offline use). Distances are straight-line (haversine), not road distance.
* Analysts are deliberately read-only on approvals and dispatch; this is a policy choice you can change in `core/tasks.py`.
* Estimated gains are conservative per-unit lower bounds and are **not comparable across risk-appetite settings**.
* Business Case numbers come from simulated chains (net gain positive in 5/5, 0.4-3.4% of baseline contribution). Run a pilot on real data.
* Sales are used as demand (stock-outs hide true demand); promotions and launches are not modelled; discount response is a user assumption.
* Transfers may be restricted by drug-licence / cold-chain rules; confirm with compliance. Return terms are assumptions you set.
* Backtest/accuracy reporting needs 18+ months of history; with less, the over-dispersion parameter is assumed.
=======
# EXPIRY-GUIDE
Developed a Streamlit-based pharmacy inventory management platform that uses machine learning to forecast product demand, identify expiry risks, and optimize stock transfers, returns, and markdowns. Implemented data validation, interactive dashboards, risk analysis, automated reporting to reduce inventory losses and improve stock management.
>>>>>>> fba24f3f040ad7f760de171229157c6c61a1ac3a
