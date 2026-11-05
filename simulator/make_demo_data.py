"""Generate demo upload files (the same format real users upload). Run: python simulator/make_demo_data.py"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
from config import START_DATE
from world import make_world, simulate_demand, Sim
from policies import Baseline

OUT = os.path.join(os.path.dirname(__file__), "..", "sample_data")


def export(sim, w, o, folder):
    os.makedirs(f"{OUT}/{folder}", exist_ok=True)
    start = pd.Timestamp(START_DATE); sk, st = w["skus"], w["stores"]
    t_, s_, k_ = np.nonzero(sim.S[:o])
    pd.DataFrame({"date": (start + pd.to_timedelta(t_, "D")).strftime("%Y-%m-%d"), "store": st.store.values[s_], "sku": sk.sku.values[k_],
                  "units": sim.S[t_, s_, k_]}).to_csv(f"{OUT}/{folder}/sales.csv.gz", index=False)
    bt = sim.batch_table()
    pd.DataFrame({"store": st.store.values[bt.s], "sku": sk.sku.values[bt.k], "batch_id": [f"B{b:06d}" for b in bt.bid],
                  "expiry_date": (start + pd.to_timedelta(bt.exp.values, "D")).strftime("%Y-%m-%d"), "quantity": bt.qty}).to_csv(f"{OUT}/{folder}/inventory.csv", index=False)
    sk[["sku", "category", "unit_cost", "unit_price"]].to_csv(f"{OUT}/{folder}/skus.csv", index=False)
    st[["store", "lat", "lon"]].round(5).to_csv(f"{OUT}/{folder}/stores.csv", index=False)
    print(folder, "as of", (start + pd.Timedelta(days=o)).date(), "| sales rows", len(t_), "| batches", len(bt))


w = make_world(42); D, lam, lu = simulate_demand(w, 42)
sim = Sim(w, D, lu); sim.run(Baseline(), 0, 900, stop_before_decide=900); export(sim, w, 900, "demo_a_jun2024")
sim.run(Baseline(), 900, 930, decide_at_start=True); export(sim, w, 930, "demo_b_jul2024")
