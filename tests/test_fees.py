from datetime import date

from app.fees import cat_llc_rate_per_share, finra_taf_per_share, finra_taf_terms, regulatory_fees, sec_rate_per_million


def test_effective_dated_sec_rates():
    assert sec_rate_per_million(date(2024, 5, 21)) == 8.0
    assert sec_rate_per_million(date(2024, 5, 22)) == 27.8
    assert sec_rate_per_million(date(2025, 5, 14)) == 0.0
    assert sec_rate_per_million(date(2026, 4, 4)) == 20.6


def test_finra_rate_and_cap_change_in_2026():
    assert finra_taf_terms(date(2025, 12, 31)) == (0.000166, 8.30)
    assert finra_taf_terms(date(2026, 1, 1)) == (0.000195, 9.79)
    assert finra_taf_per_share(date(2026, 1, 1)) == 0.000195


def test_regulatory_fees_round_up_to_cents():
    fees = regulatory_fees(date(2024, 6, 1), 41, 500, 550)
    assert fees["sec"] == 0.02
    assert fees["taf"] == 0.01
    assert fees["total"] == fees["sec"] + fees["taf"] + fees["cat"]


def test_taf_is_capped_for_extreme_low_price_share_counts():
    fees = regulatory_fees(date(2024, 6, 1), 100_000, 500, 500)
    assert fees["taf"] == 8.30


def test_taf_is_exempt_when_execution_price_is_below_rate():
    fees = regulatory_fees(date(2024, 6, 1), 10_000_000, 500, 500)
    assert fees["taf"] == 0.0


def test_effective_dated_cat_llc_rates():
    assert cat_llc_rate_per_share(date(2024, 8, 31)) == 0.0
    assert cat_llc_rate_per_share(date(2024, 9, 1)) == 0.000035
    assert cat_llc_rate_per_share(date(2025, 1, 1)) == 0.000022
    assert cat_llc_rate_per_share(date(2025, 7, 1)) == 0.000009
    assert cat_llc_rate_per_share(date(2026, 4, 19)) == 0.000009
