from app.ledger import fees_for_trade


def test_commission_floor():
    c, s, t = fees_for_trade("buy", 1000, 0.00025, 5, 0.0005, 0.00001)
    assert c == 5
    assert s == 0
    assert abs(t - 0.01) < 1e-9


def test_sell_stamp():
    c, s, t = fees_for_trade("sell", 100_000, 0.00025, 5, 0.0005, 0.00001)
    assert c == 25
    assert s == 50
    assert abs(t - 1.0) < 1e-9
