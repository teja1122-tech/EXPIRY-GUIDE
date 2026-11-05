"""Central configuration. Every business assumption lives here so it can be challenged and changed."""
import numpy as np

# ---- World size (synthetic chain) ----
N_STORES, N_SKUS = 10, 40
START_DATE = "2022-01-01"
T_GOLIVE = 900          # day index when the system "goes live"; everything before is history
T_END = 1080            # end of the replay window (180 days after go-live)
HORIZON = 120           # forecast / risk horizon in days (we act on batches expiring within this)

# ---- Replenishment behaviour of the chain today (baseline) ----
LEAD = 2                # supplier lead time (days)
REVIEW = 7              # each store reviews stock once a week (staggered by store)
SAFETY_DAYS = 7
MIN_DISPLAY = 6         # minimum shelf stock per SKU per store (units)

# ---- Economics ----
RETURN_CREDIT = 0.60    # distributor credits 60% of cost on returned stock ...
RETURN_MIN_DAYS = 60    # ... only if >= 60 days of shelf life remain
LANE_FIXED = 60.0       # Rs per store-to-store shipment lane per day
LANE_PER_KM = 6.0       # Rs per km
UNIT_HANDLING = 1.0     # Rs per unit moved
RETURN_HANDLING = 0.5   # Rs per unit returned

# ---- Decision thresholds ----
THETA_SRC = 0.30        # a unit is "at risk" if its chance of selling at its own store <= 30%
THETA_DST = 0.70        # a receiving store may only take units it will sell with >= 70% probability
KEEP_LATER = 0.50       # do not push the receiver's own later batches below 50% sell-through

# ---- Demand model of the simulated world ----
NB_R = 8                # negative-binomial shape for daily demand (over-dispersed vs Poisson)
CATS = ["Antibiotic", "Fever & Pain", "Cough & Cold", "Chronic", "Vitamins",
        "Dermatology", "Gastro", "Allergy"]
SEAS = {  # (amplitude, peak day-of-year)
    "Antibiotic": (0.25, 225), "Fever & Pain": (0.35, 230), "Cough & Cold": (0.45, 15),
    "Chronic": (0.0, 0), "Vitamins": (0.10, 15), "Dermatology": (0.30, 150),
    "Gastro": (0.20, 220), "Allergy": (0.40, 90)}
DOW_FACTOR = np.array([1.05, 1.0, 1.0, 1.0, 1.02, 1.10, 0.85])   # Mon..Sun
TRANSFER_MIN_DAYS = 21  # do not move batches with < 21 days left (not worth the handling, receiver cannot sell them)
