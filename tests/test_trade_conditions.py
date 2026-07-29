from app.trade_conditions import price_updating_trade
from app.simulation import _quote


def test_odd_lot_and_out_of_sequence_trades_do_not_update_price():
    assert price_updating_trade({"z": "C", "c": ["@", "I"]}) is False
    assert price_updating_trade({"z": "A", "c": ["Z"]}) is False


def test_regular_and_reopening_trades_update_price():
    assert price_updating_trade({"z": "C", "c": ["@"]}) is True
    assert price_updating_trade({"z": "A", "c": ["5"]}) is True


def test_unknown_condition_is_rejected_conservatively():
    assert price_updating_trade({"z": "C", "c": ["?"]}) is False


def test_alpaca_quote_sizes_are_converted_from_round_lots_to_shares():
    _bid, _ask, bid_size, ask_size = _quote({"bp": 10, "ap": 10.1, "bs": 2, "as": 3})
    assert bid_size == 200
    assert ask_size == 300
