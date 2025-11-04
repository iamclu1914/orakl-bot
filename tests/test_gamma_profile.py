from datetime import datetime, timedelta

import math

from src.utils.gamma_profile import compute_gamma_profile


def _future_date(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).date().isoformat()


def test_compute_gamma_profile_basic():
    contracts = [
        {
            "details": {
                "strike_price": 100,
                "contract_type": "call",
                "expiration_date": _future_date(5),
            },
            "open_interest": 1000,
            "greeks": {"gamma": 0.02},
            "underlying_asset": {"price": 100},
            "implied_volatility": 0.30,
        },
        {
            "details": {
                "strike_price": 105,
                "contract_type": "call",
                "expiration_date": _future_date(10),
            },
            "open_interest": 500,
            "greeks": {"gamma": 0.01},
            "underlying_asset": {"price": 100},
            "implied_volatility": 0.25,
        },
        {
            "details": {
                "strike_price": 95,
                "contract_type": "put",
                "expiration_date": _future_date(7),
            },
            "open_interest": 800,
            "greeks": {"gamma": 0.03},
            "underlying_asset": {"price": 100},
            "implied_volatility": 0.28,
        },
    ]

    profile = compute_gamma_profile(contracts, spot_price=100)

    assert profile is not None

    expected_call_gamma = 0.02 * 1000 * 100 * (100 ** 2) + 0.01 * 500 * 100 * (100 ** 2)
    expected_put_gamma = -0.03 * 800 * 100 * (100 ** 2)

    assert math.isclose(profile["call_gamma_total"], expected_call_gamma, rel_tol=1e-9)
    assert math.isclose(profile["put_gamma_total"], expected_put_gamma, rel_tol=1e-9)
    assert math.isclose(
        profile["net_gamma_total"], expected_call_gamma + expected_put_gamma, rel_tol=1e-9
    )

    assert profile["call_wall"]["strike"] == 100
    assert profile["put_wall"]["strike"] == 95

    assert profile["total_call_oi"] == 1500
    assert profile["total_put_oi"] == 800

    expected_move = profile["expected_move"]
    assert expected_move is not None and expected_move > 0


def test_compute_gamma_profile_missing_data_returns_none():
    assert compute_gamma_profile([], spot_price=100) is None
    assert compute_gamma_profile([{"details": {}}], spot_price=0) is None

