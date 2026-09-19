"""Offline, synthetic field maps only; no service or private invoice needed."""
from decimal import Decimal
import pytest
from app.core.errors import InputError
from app.evaluation.fields import evaluate_fields


def status(field, expected, predicted, *, azure=False):
    reference = {field: expected}
    if field == "buyer_identity":
        reference["is_total_cost_equal_to_or_higher_than_1000"] = True
    result = evaluate_fields(reference, {field: predicted}, prediction_format="azure" if azure else "plain")
    return result["fields"][field]["status"]


@pytest.mark.parametrize("field,expected,predicted", [
    ("document_type", "tax_invoice", "Tax Invoice"),
    ("document_number", "0001", "00 01"),
    ("seller_abn", "00000000000", "00 000 000 000"),
    ("total_cost", Decimal("1000"), "$1,000.00"),
    ("gst", Decimal("10"), "10.00 AUD"),
    ("date_of_issue", "2026-09-19", "19 September 2026"),
    ("date_of_expense", "2026-09-19", "19/09/2026"),
    ("payment_due_date", "2026-09-19", "2026-09-19"),
    ("paid", False, False), ("gst", Decimal("0"), 0),
    ("supply_type", "services", "services"),
    ("expense_category", "food", "food"),
    ("taxable_sale_extent", Decimal("100"), "100.00"),
])
def test_field_specific_normalization(field, expected, predicted):
    assert status(field, expected, predicted) == "correct"


@pytest.mark.parametrize("field,expected,predicted", [
    ("seller_business_name", "FAKE Seller", "fake seller"),
    ("document_number", "0001", "001"),
    ("paid", True, 1), ("paid", False, "false"),
    ("date_of_issue", "2026-03-04", "03/04/2026"),
    ("supply_type", "services", "service"),
    ("expense_category", "food", "Food"),
    ("total_cost", "123", "1,23"),
    ("gst", "0", "NaN"),
])
def test_non_matches(field, expected, predicted):
    assert status(field, expected, predicted) == "incorrect"


@pytest.mark.parametrize("prediction", [None, {}, {"type": "string"}, {"source": None, "valueString": None}, {"source": [], "valueString": ""}])
def test_azure_not_found_requires_no_source_and_no_value(prediction):
    assert status("document_number", None, prediction, azure=True) == "correct"


@pytest.mark.parametrize("prediction", [{"source": "FAKE span"}, {"valueString": "FAKE"}, {"valueNumber": 0}, {"valueBoolean": False}, {"valueString": "", "source": "FAKE span"}])
def test_azure_no_value_string_alone_does_not_mean_missing(prediction):
    assert status("document_number", None, prediction, azure=True) == "incorrect"


def test_azure_real_false_and_zero():
    assert status("paid", False, {"valueBoolean": False}, azure=True) == "correct"
    assert status("gst", 0, {"valueNumber": 0}, azure=True) == "correct"
    assert status("document_number", "001", {"valueString": "001", "valueNumber": 1}, azure=True) == "incorrect"


def test_buyer_dependency_uses_ground_truth_not_prediction():
    result = evaluate_fields({"is_total_cost_equal_to_or_higher_than_1000": True, "buyer_identity": "FAKE Buyer"}, {"is_total_cost_equal_to_or_higher_than_1000": False, "buyer_identity": ""})
    assert result["fields"]["buyer_identity"]["status"] == "incorrect"
    result = evaluate_fields({"is_total_cost_equal_to_or_higher_than_1000": False, "buyer_identity": ""}, {"buyer_identity": "FAKE"})
    assert result["fields"]["buyer_identity"]["status"] == "not_applicable"
    result = evaluate_fields({"buyer_identity": ""}, {})
    assert result["fields"]["buyer_identity"]["status"] == "dependency_unknown"


def test_unannotated_is_not_credited_as_correct_and_no_content_in_report():
    result = evaluate_fields({"document_number": "FAKE_SECRET"}, {})
    assert result["evaluated"] == 1
    assert result["incorrect"] == 1
    assert "FAKE_SECRET" not in str(result)
    assert result["fields"]["paid"]["status"] == "not_annotated"


def test_azure_envelope_and_buyer_empty_string():
    result = evaluate_fields({"paid": True}, {"fields": {"paid": {"valueBoolean": True}}}, prediction_format="azure")
    assert result["correct"] == 1
    assert status("buyer_identity", "", {}, azure=True) == "correct"
    assert status("buyer_identity", "", {"source": "FAKE"}, azure=True) == "incorrect"


@pytest.mark.parametrize("reference,prediction,fmt", [
    ({"nature_of_expense": "goods"}, {}, "plain"),
    ({}, {"nature_of_expense": "goods"}, "plain"),
    ({}, {"fields": []}, "azure"), ({}, {}, "bad"),
    ({"paid": "false"}, {}, "plain"),
])
def test_invalid_evaluation_contract(reference, prediction, fmt):
    with pytest.raises(InputError):
        evaluate_fields(reference, prediction, prediction_format=fmt)


def test_evaluation_script_local_output_and_safe_errors(repo, monkeypatch, capsys):
    from scripts import evaluate_fields as script
    from app.core.files import write_json, read_json
    monkeypatch.setattr(script, "ROOT", repo)
    write_json(repo / "expected.json", {"document_number": "FAKE_SECRET"})
    write_json(repo / "predicted.json", {"document_number": "FAKE_SECRET"})
    args = ["--expected", "expected.json", "--predicted", "predicted.json", "--run-id", "evaluation-test"]
    assert script.main(args) == 0
    assert read_json(repo / "outputs/evaluation-test/evaluation.json")["correct"] == 1
    assert script.main(args) == 1
    assert script.main(["--expected", "../outside.json", "--predicted", "predicted.json"]) == 1
    captured = capsys.readouterr()
    assert "FAKE_SECRET" not in captured.out + captured.err


@pytest.mark.parametrize("value", [[], {}, False, 0])
def test_plain_malformed_or_zero_values_are_not_missing(value):
    assert status("document_number", None, value) == "incorrect"


def test_combined_currency_prefix():
    assert status("total_cost", "1000", "AUD $1,000.00") == "correct"
