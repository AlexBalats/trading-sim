from sim.market import update_prices


def test_no_sales_no_change():
    assert update_prices({"X": 7.0}, {"X": []}, k=3) == {"X": 7.0}


def test_one_sale_nudges():
    # w = 1 / (1 + 3) = 0.25, so 7 + 0.25 * (11 - 7) = 8
    assert update_prices({"X": 7.0}, {"X": [11.0]}, k=3)["X"] == 8.0


def test_median_of_even_count():
    # median of 4, 6, 10, 20 is 8; w = 4 / 7
    new = update_prices({"X": 1.0}, {"X": [20.0, 4.0, 10.0, 6.0]}, k=3)["X"]
    assert abs(new - (1 + 4 / 7 * (8 - 1))) < 1e-9


def test_many_sales_move_most_of_the_way():
    new = update_prices({"X": 10.0}, {"X": [20.0] * 97}, k=3)["X"]
    assert abs(new - 19.7) < 1e-9          # w = 97/100


def test_cards_without_entries_unchanged():
    assert update_prices({"X": 5.0, "Y": 2.0}, {"X": [9.0]}, k=3)["Y"] == 2.0
