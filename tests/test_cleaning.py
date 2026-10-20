from pipelines import clean_ubereats as clean


def test_item_spellings_are_merged():
    items = clean.clean_items()
    names = items["item"].str.lower()
    assert names.is_unique
    assert not items["item"].str.contains("  ").any()


def test_trading_night_assignment():
    hourly = clean.clean_hourly().set_index(["day", "hour"])
    assert hourly.loc[("Sun", 4), "trading_night"] == "Sat"
    assert hourly.loc[("Sat", 22), "trading_night"] == "Sat"


def test_reviews_drop_internal_ids():
    reviews = clean.clean_reviews()
    assert "order_uuid" not in reviews.columns and "store_uuid" not in reviews.columns
