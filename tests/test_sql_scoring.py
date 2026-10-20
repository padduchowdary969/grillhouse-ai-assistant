"""The golden-set scorer must be neither too strict nor too lenient, or the model comparison means nothing."""

from decimal import Decimal

from evals.evaluate_sql import matches


def test_extra_columns_and_names_are_ignored():
    assert matches([("Sat",)], [("Sat", Decimal("18.3"), 1200)])


def test_rounding_differences_pass():
    assert matches([(Decimal("33.2"),)], [(33.21,)])


def test_single_row_answer_uses_first_row():
    assert matches([("Sat",)], [("Sat",), ("Fri",), ("Sun",)])


def test_wrong_values_fail():
    assert not matches([("Sat",)], [("Fri",)])
    assert not matches([(Decimal("155347.63"),)], [(Decimal("154000.00"),)])


def test_missing_rows_fail():
    vegan = [("Chilli Sauce",), ("Cola",), ("Fries",)]
    assert not matches(vegan, [("Cola",), ("Fries",)])


def test_row_order_does_not_matter_for_sets():
    assert matches([("a", 1), ("b", 2)], [("b", 2), ("a", 1)])
