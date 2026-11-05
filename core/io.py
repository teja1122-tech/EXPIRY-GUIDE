"""Data ingestion: templates, flexible column names, validation, and conversion to model-ready arrays."""
import hashlib
from dataclasses import dataclass, field
import numpy as np, pandas as pd

ALIASES = {
    "sales": {"date": ["sale_date", "day", "invoice_date", "bill_date"], "store": ["store_id", "branch", "outlet", "store_name"],
              "sku": ["sku_id", "item", "product", "product_id", "drug", "item_code"], "units": ["qty", "quantity", "units_sold", "sold"]},
    "inventory": {"store": ["store_id", "branch", "outlet", "store_name"], "sku": ["sku_id", "item", "product", "product_id", "drug", "item_code"],
                  "batch_id": ["batch", "batch_no", "lot", "lot_no"], "expiry_date": ["expiry", "exp_date", "expiry_dt", "exp"],
                  "quantity": ["qty", "units", "on_hand", "stock", "closing_stock"]},
    "skus": {"sku": ["sku_id", "item", "product", "product_id", "drug", "item_code"], "category": ["cat", "group", "therapeutic_class"],
             "unit_cost": ["cost", "purchase_price", "cost_price", "ptr"], "unit_price": ["price", "mrp", "selling_price", "sale_price"]},
    "stores": {"store": ["store_id", "branch", "outlet", "store_name"], "lat": ["latitude"], "lon": ["lng", "longitude", "long"]},
}
REQUIRED = {"sales": ["date", "store", "sku", "units"], "inventory": ["store", "sku", "expiry_date", "quantity"],
            "skus": ["sku", "unit_cost"], "stores": ["store"]}


class DataError(Exception):
    def __init__(self, msgs): self.msgs = msgs if isinstance(msgs, list) else [msgs]; super().__init__("; ".join(self.msgs))


def template_frames():
    return {
        "sales": pd.DataFrame({"date": ["2024-05-01", "2024-05-01", "2024-05-02"], "store": ["Store-01", "Store-02", "Store-01"],
                               "sku": ["SKU-001", "SKU-001", "SKU-002"], "units": [3, 1, 5]}),
        "inventory": pd.DataFrame({"store": ["Store-01", "Store-02"], "sku": ["SKU-001", "SKU-001"], "batch_id": ["B1001", "B1002"],
                                   "expiry_date": ["2024-09-30", "2025-02-28"], "quantity": [40, 20]}),
        "skus": pd.DataFrame({"sku": ["SKU-001", "SKU-002"], "category": ["Antibiotic", "Chronic"], "unit_cost": [42.5, 18.0], "unit_price": [55.0, 24.0]}),
        "stores": pd.DataFrame({"store": ["Store-01", "Store-02"], "lat": [17.41, 17.36], "lon": [78.45, 78.52]}),
    }


def read_table(f):
    name = str(getattr(f, "name", f)).lower()
    if name.endswith((".xlsx", ".xls")): return pd.read_excel(f)
    if name.endswith(".gz"): return pd.read_csv(f, compression="gzip")
    return pd.read_csv(f)


def _canon(df, kind):
    low = {str(c).strip().lower().replace(" ", "_"): c for c in df.columns}; m = {}
    for canon, al in ALIASES[kind].items():
        for a in [canon] + al:
            if a in low: m[low[a]] = canon; break
    return df.rename(columns=m)[[c for c in df.rename(columns=m).columns if c in ALIASES[kind]]].copy()


@dataclass
class Dataset:
    start: pd.Timestamp; as_of: pd.Timestamp; T: int
    stores: pd.DataFrame; skus: pd.DataFrame; S: np.ndarray
    batches: pd.DataFrame; expired: pd.DataFrame; dist: object
    issues: list = field(default_factory=list); quality: float = 100.0; quality_notes: list = field(default_factory=list)
    fingerprint: str = ""
    geo_hash: str = ""
    @property
    def N(self): return self.S.shape[1]
    @property
    def K(self): return self.S.shape[2]
    @property
    def cost(self): return self.skus.unit_cost.values
    @property
    def price(self): return self.skus.unit_price.values


def _haversine(lat, lon):
    lat, lon = np.radians(lat), np.radians(lon)
    a = np.sin((lat[:, None]-lat[None])/2)**2 + np.cos(lat[:, None])*np.cos(lat[None])*np.sin((lon[:, None]-lon[None])/2)**2
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def geo_fingerprint(stores):
    return hashlib.md5(stores[["store", "lat", "lon"]].round(5).to_csv(index=False).encode()).hexdigest()[:8]


def recompute_geo(ds):
    """Recompute distances from ds.stores coordinates (call after editing locations)."""
    ok = ds.stores.lat.notna().all() and ds.stores.lon.notna().all()
    ds.dist = _haversine(ds.stores.lat.values.astype(float), ds.stores.lon.values.astype(float)) if ok else None
    ds.geo_hash = geo_fingerprint(ds.stores)
    return ds


def build_dataset(sales, inventory, skus, stores=None, as_of=None):
    issues, errs = [], []
    def note(level, msg): issues.append({"level": level, "message": msg})
    raw = {"sales": sales, "inventory": inventory, "skus": skus}
    if stores is not None: raw["stores"] = stores
    tabs = {}
    for kind, df in raw.items():
        t = _canon(df, kind); miss = [c for c in REQUIRED[kind] if c not in t.columns]
        if miss: errs.append(f"{kind}: missing required column(s) {miss}. Found: {list(df.columns)[:10]}")
        tabs[kind] = t
    if errs: raise DataError(errs)
    bad_rows = 0; total_rows = 0
    # ---- SKU master
    sk = tabs["skus"].copy(); sk["sku"] = sk.sku.astype(str).str.strip(); sk["unit_cost"] = pd.to_numeric(sk.unit_cost, errors="coerce")
    n0 = len(sk); sk = sk.drop_duplicates("sku"); sk = sk[sk.unit_cost > 0]
    if len(sk) < n0: note("warning", f"SKU master: {n0-len(sk)} row(s) dropped (duplicate SKU or unit_cost missing/<=0).")
    if "category" not in sk: sk["category"] = "Uncategorized"; note("info", "No category column - using 'Uncategorized'. Add one for category heatmaps.")
    sk["category"] = sk.category.fillna("Uncategorized").astype(str)
    if "unit_price" not in sk or sk.unit_price.isna().all():
        sk["unit_price"] = (sk.unit_cost*1.3).round(2); note("info", "No unit_price column - assumed price = cost x 1.3.")
    sk["unit_price"] = pd.to_numeric(sk.unit_price, errors="coerce").fillna(sk.unit_cost*1.3)
    sk = sk[["sku", "category", "unit_cost", "unit_price"]].sort_values("sku").reset_index(drop=True)
    if sk.empty: raise DataError("SKU master has no usable rows.")
    # ---- sales
    s = tabs["sales"].copy(); total_rows += len(s)
    s["date"] = pd.to_datetime(s.date, errors="coerce"); s["units"] = pd.to_numeric(s.units, errors="coerce")
    s["store"] = s.store.astype(str).str.strip(); s["sku"] = s.sku.astype(str).str.strip()
    bad = s.date.isna() | s.units.isna(); neg = s.units < 0
    if bad.sum(): note("warning", f"Sales: {int(bad.sum())} row(s) dropped (unreadable date or units).")
    if neg.sum(): note("warning", f"Sales: {int(neg.sum())} row(s) with negative units dropped (returns/adjustments?).")
    bad_rows += int(bad.sum() + neg.sum()); s = s[~bad & ~neg]
    unk = ~s.sku.isin(sk.sku)
    if unk.sum(): note("warning", f"Sales: {int(unk.sum())} row(s) for {s[unk].sku.nunique()} SKU(s) not in SKU master were ignored (e.g. {', '.join(s[unk].sku.unique()[:4])}).")
    bad_rows += int(unk.sum()); s = s[~unk]
    if s.empty: raise DataError("No usable sales rows after cleaning.")
    start = s.date.min().normalize(); last = s.date.max().normalize()
    as_of = pd.Timestamp(as_of).normalize() if as_of is not None else last + pd.Timedelta(days=1)
    T = int((as_of - start).days)
    if T < 45: raise DataError(f"Only {T} days of sales history - at least 45 days are needed to forecast.")
    s = s[s.date < as_of]
    # ---- inventory
    iv = tabs["inventory"].copy(); total_rows += len(iv)
    iv["store"] = iv.store.astype(str).str.strip(); iv["sku"] = iv.sku.astype(str).str.strip()
    iv["expiry_date"] = pd.to_datetime(iv.expiry_date, errors="coerce"); iv["quantity"] = pd.to_numeric(iv.quantity, errors="coerce")
    if "batch_id" not in iv: iv["batch_id"] = [f"AUTO-{i+1}" for i in range(len(iv))]; note("info", "No batch_id column - batches were numbered automatically.")
    iv["batch_id"] = iv.batch_id.astype(str)
    bad = iv.expiry_date.isna() | iv.quantity.isna() | (iv.quantity <= 0)
    if bad.sum(): note("warning", f"Inventory: {int(bad.sum())} row(s) dropped (unreadable expiry, or quantity missing/<=0).")
    bad_rows += int(bad.sum()); iv = iv[~bad]
    unk = ~iv.sku.isin(sk.sku)
    if unk.sum(): note("warning", f"Inventory: {int(unk.sum())} row(s) for SKUs not in SKU master were ignored (e.g. {', '.join(iv[unk].sku.unique()[:4])}).")
    bad_rows += int(unk.sum()); iv = iv[~unk]
    if iv.empty: raise DataError("No usable inventory rows after cleaning.")
    iv["quantity"] = iv.quantity.round().astype(int)
    # ---- stores
    names = sorted(set(s.store) | set(iv.store) | (set(tabs["stores"].store.astype(str).str.strip()) if "stores" in tabs else set()))
    st = pd.DataFrame({"store": names}); coords = False
    if "stores" in tabs and {"lat", "lon"} <= set(tabs["stores"].columns):
        t = tabs["stores"].copy(); t["store"] = t.store.astype(str).str.strip(); t = t.drop_duplicates("store")
        st = st.merge(t[["store", "lat", "lon"]], on="store", how="left"); coords = st.lat.notna().all() and st.lon.notna().all()
        if not coords: note("warning", "Some stores have no coordinates - using a flat default distance between stores (set in Planning profile).")
    else:
        st["lat"] = np.nan; st["lon"] = np.nan; note("info", "No store coordinates - using a flat default distance between stores for shipping cost.")
    if len(st) < 2: note("warning", "Only one store found - transfers need at least two stores; returns and risk scoring still work.")
    sidx = {n: i for i, n in enumerate(st.store)}; kidx = {n: i for i, n in enumerate(sk.sku)}
    N, K = len(st), len(sk)
    S = np.zeros((T, N, K), np.int32)
    d = (s.date.dt.normalize() - start).dt.days.values
    np.add.at(S, (d, s.store.map(sidx).values, s.sku.map(kidx).values), s.units.round().astype(int).values)
    days_with_sales = len(set(d)); cov = days_with_sales / T
    if cov < 0.9: note("warning", f"Sales exist on only {days_with_sales} of {T} days ({100*cov:.0f}%). Missing days are treated as zero sales - check for gaps in your export.")
    # ---- batches
    iv["s"] = iv.store.map(sidx); iv["k"] = iv.sku.map(kidx)
    iv["exp"] = (iv.expiry_date.dt.normalize() - start).dt.days
    iv = iv.groupby(["s", "k", "batch_id", "exp", "expiry_date"], as_index=False).quantity.sum().rename(columns={"quantity": "qty"})
    iv = iv.sort_values(["s", "k", "exp"]).reset_index(drop=True); iv["bid"] = np.arange(len(iv))
    expired = iv[iv.exp <= T].copy(); live = iv[iv.exp > T].copy().reset_index(drop=True)
    if len(expired): note("warning", f"{len(expired)} batch(es) are already expired or expire today (value shown on Command Center). They are excluded from forecasting.")
    dist = _haversine(st.lat.values.astype(float), st.lon.values.astype(float)) if coords else None
    # ---- quality score
    q, notes = 100.0, []
    frac = bad_rows / max(1, total_rows + bad_rows)
    if frac > 0: q -= min(40, 400*frac); notes.append(f"{100*frac:.1f}% of rows were unusable")
    if T < 120: q -= 25; notes.append(f"short history ({T} days): seasonality cannot be learned")
    elif T < 365: q -= 10; notes.append(f"history under 1 year ({T} days): no seasonality learning")
    if cov < 0.9: q -= 10; notes.append("gaps in sales dates")
    if not coords: q -= 5; notes.append("no store coordinates")
    if sk.category.eq("Uncategorized").all(): q -= 3; notes.append("no categories")
    fp = hashlib.md5(S.tobytes() + live.to_csv(index=False).encode() + sk.to_csv(index=False).encode()).hexdigest()[:12]
    return Dataset(start=start, as_of=as_of, T=T, stores=st, skus=sk, S=S, batches=live, expired=expired, dist=dist, issues=issues,
                   quality=max(0.0, q), quality_notes=notes, fingerprint=fp, geo_hash=geo_fingerprint(st))
