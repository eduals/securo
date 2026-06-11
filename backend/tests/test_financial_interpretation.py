"""Unit tests for the financial interpretation resolution (pure functions)."""
from app.services.financial_interpretation import (
    EXPENSE,
    INCOME,
    baseline_financial_type,
    default_affects_reports,
    resolve_affects_reports,
    resolve_financial_type,
)


def test_baseline_is_uniform_credit_is_income_even_for_credit_card():
    # Uniform baseline: the credit-card sign is normalized at import, not guessed
    # here, so credit_card behaves like any account at the baseline level.
    assert baseline_financial_type("credit_card", "credit") == INCOME


def test_baseline_credit_card_debit_is_expense():
    assert baseline_financial_type("credit_card", "debit") == EXPENSE


def test_baseline_checking_credit_is_income():
    assert baseline_financial_type("checking", "credit") == INCOME


def test_baseline_checking_debit_is_expense():
    assert baseline_financial_type("checking", "debit") == EXPENSE


def test_baseline_unknown_account_type_defaults_like_checking():
    assert baseline_financial_type(None, "credit") == INCOME
    assert baseline_financial_type("savings", "debit") == EXPENSE


def test_resolve_precedence_transaction_wins():
    # tx override beats category default beats baseline
    assert resolve_financial_type(
        tx_financial_type="transfer",
        category_default="income",
        account_type="checking",
        raw_type="credit",
    ) == "transfer"


def test_resolve_precedence_category_default_when_no_tx():
    assert resolve_financial_type(
        tx_financial_type=None,
        category_default="transfer",
        account_type="credit_card",
        raw_type="credit",
    ) == "transfer"


def test_resolve_falls_back_to_baseline():
    assert resolve_financial_type(
        tx_financial_type=None,
        category_default=None,
        account_type="credit_card",
        raw_type="debit",
    ) == EXPENSE


def test_affects_reports_neutral_types_false():
    assert default_affects_reports("transfer") is False
    assert default_affects_reports("adjustment") is False
    assert default_affects_reports("ignored") is False


def test_affects_reports_income_expense_true():
    assert default_affects_reports("income") is True
    assert default_affects_reports("expense") is True


def test_resolve_affects_reports_precedence():
    # explicit tx flag wins
    assert resolve_affects_reports(
        tx_affects_reports=True, category_default_affects=False, financial_type="transfer"
    ) is True
    # category default next
    assert resolve_affects_reports(
        tx_affects_reports=None, category_default_affects=False, financial_type="income"
    ) is False
    # else derived from financial_type
    assert resolve_affects_reports(
        tx_affects_reports=None, category_default_affects=None, financial_type="adjustment"
    ) is False
