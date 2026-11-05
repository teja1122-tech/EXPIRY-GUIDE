"""Planning parameters. Every business assumption is a field so users can change it in the UI."""
from dataclasses import dataclass, asdict, replace

HORIZON = 120


@dataclass(frozen=True)
class Params:
    theta_src: float = 0.30        # unit is "at risk" if P(sells at own store) <= this
    theta_dst: float = 0.70        # receiver must sell the unit with >= this probability
    keep_later: float = 0.50       # do not push receiver's later batches below this sell-through
    return_credit: float = 0.60    # distributor credit as a share of unit cost
    return_min_days: int = 60      # distributor accepts returns only with >= this many days left
    transfer_min_days: int = 21    # do not move batches with fewer days left
    lane_fixed: float = 60.0       # fixed cost per store-to-store shipment lane
    lane_per_km: float = 6.0
    unit_handling: float = 1.0
    return_handling: float = 0.5
    default_distance_km: float = 15.0   # used when store coordinates are not uploaded
    allow_transfers: bool = True
    allow_returns: bool = True
    max_transfer_km: float = 0.0          # 0 = no distance limit
    blocked_receivers: tuple = ()         # stores that must not receive transfers (closed, no cold chain...)
    blocked_senders: tuple = ()           # stores that must not send transfers

    def as_dict(self): return asdict(self)


PRESETS = {
    "Balanced (default)": Params(),
    "Conservative": Params(theta_src=0.20, theta_dst=0.80, keep_later=0.60, return_credit=0.60),
    "Aggressive recovery": Params(theta_src=0.45, theta_dst=0.60, keep_later=0.40, lane_fixed=40.0),
    "Transfers only": Params(allow_returns=False),
    "Returns only": Params(allow_transfers=False),
}
