import pytest

from pipelines.redact import redact


@pytest.mark.parametrize("text, hidden, mask", [
    ("Call me on 07700 900461 to sort a refund", "07700 900461", "<PHONE>"),
    ("ring +44 7700 900123", "7700 900123", "<PHONE>"),
    ("email me at jo.bloggs@example.com", "jo.bloggs@example.com", "<EMAIL>"),
    ("Deliver to M1 4BT please", "M1 4BT", "<POSTCODE>"),
    ("Flat 4, 12 Example Street", "Example Street", "<ADDRESS>"),
    ("ask for Priya Shah at the door", "Priya Shah", "<NAME>"),
])
def test_personal_details_are_masked(text, hidden, mask):
    result = redact(text)
    assert hidden not in result
    assert mask in result


@pytest.mark.parametrize("text", [
    "Halloumi Burger was cold",
    "Crispy hot wings were very tasty",
    "Double Smash Burger and Peri Peri Loaded Fries were amazing",
    "Took 45 minutes, 2 stars",
    "Order 12345678 missing",
])
def test_food_and_numbers_are_left_alone(text):
    assert redact(text) == text


def test_empty_text():
    assert redact("") == ""
