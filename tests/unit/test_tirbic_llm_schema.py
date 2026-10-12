"""Synthetic v3 contract checks shared by Qwen, Gemini and GPT; no model calls."""
from decimal import Decimal
import json

import pytest

from app.core.errors import ExtractionError, InputError
from app.core.files import json_text
from app.evaluation.fields import evaluate_fields
from app.extraction.block_contract import assess, ocr_blocks
from app.gemini.contract import build_request as gemini_request
from app.llm.contract import assess_response, build_messages
from app.openai_extraction.config import OpenAISettings
from app.openai_extraction.contract import build_request as openai_request
from app.schemas.invoice import TaxInvoice
from app.schemas.tirbic_llm import (
    FIELDS, MISSING_REASONS, FIELD_INSTRUCTIONS, SCHEMA_VERSION, THRESHOLD,
    invoice_schema, missing_invoice,
)

SOURCE = "SYNTHETIC Tax Invoice Total AUD 1000.00 GST 0.00 Taxable: 75%"
DOCUMENT = ocr_blocks([{"res": {"parsing_res_list": [{"block_content": SOURCE}]}}])


def envelopes(invoice):
    return ({"invoice": invoice, "currency": "AUD", "evidence": {f: [] for f in FIELDS}},
            {"invoice": invoice, "currency": "AUD", "evidence": {f: [] for f in FIELDS}})


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("reason", MISSING_REASONS)
def test_all_providers_accept_exact_reasons_with_explicit_buyer_exception(field, reason):
    values = missing_invoice()
    values[field] = reason
    qwen, cloud = envelopes(values)
    invoice, validation, review = assess(json_text(cloud), DOCUMENT)
    if field == "buyer_identity" and reason == "not_found":
        assert invoice is None and not validation["valid"]
        with pytest.raises(ExtractionError):
            assess_response(json_text(qwen), SOURCE)
    else:
        result = assess_response(json_text(qwen), SOURCE)
        assert invoice == result.invoice.model_dump(mode="python") == values
        assert validation["valid"] and not review["semantic_accuracy_verified"]
        assert field in review["fields_requiring_review"]


@pytest.mark.parametrize("field", FIELDS)
def test_no_provider_accepts_legacy_null_or_omitted_keys(field):
    values = missing_invoice()
    for operation in ("null", "omit"):
        altered = dict(values)
        if operation == "null":
            altered[field] = None
        else:
            del altered[field]
        qwen, cloud = envelopes(altered)
        assert assess(json_text(cloud), DOCUMENT)[0] is None
        with pytest.raises(ExtractionError):
            assess_response(json_text(qwen), SOURCE)


@pytest.mark.parametrize("value", [0, 1, Decimal("0.75")])
def test_fraction_zero_and_one_are_values_not_missing(value):
    values = missing_invoice()
    values.update(taxable_sale_extent=value, total_cost="0.00", gst="0.00", paid=False)
    values[THRESHOLD] = False
    qwen, cloud = envelopes(values)
    result = assess_response(json_text(qwen), SOURCE)
    assert result.invoice.taxable_sale_extent == value
    assert "taxable_sale_extent" not in result.review["missing_fields"]
    assert assess(json_text(cloud), DOCUMENT)[0] == values


@pytest.mark.parametrize("value", [100, Decimal("1.01"), -1, "1.0", True])
def test_outdated_percentages_and_coercions_are_rejected(value):
    values = missing_invoice()
    values["taxable_sale_extent"] = value
    qwen, cloud = envelopes(values)
    assert assess(json_text(cloud), DOCUMENT)[0] is None
    with pytest.raises(ExtractionError):
        assess_response(json_text(qwen), SOURCE)


def test_shared_definitions_and_invoice_schema_are_identical():
    qwen = build_messages(SOURCE)[0]["content"]
    gemini = gemini_request(DOCUMENT, 8192)
    gpt = openai_request(DOCUMENT, OpenAISettings())
    assert all(FIELD_INSTRUCTIONS in text for text in (
        qwen, gemini["systemInstruction"]["parts"][0]["text"], gpt["instructions"]))
    assert json.dumps(invoice_schema(), ensure_ascii=False) in qwen
    assert gemini["generationConfig"]["responseJsonSchema"]["properties"]["invoice"] == invoice_schema()
    assert gpt["text"]["format"]["schema"]["properties"]["invoice"] == invoice_schema()
    assert "100% => 1.0" in FIELD_INSTRUCTIONS
    assert "Without supplied" in FIELD_INSTRUCTIONS
    assert "Python never repairs" in FIELD_INSTRUCTIONS


def test_no_provider_replaces_wrong_flag_or_missing_reason():
    values = missing_invoice()
    values.update(total_cost="1000.00", taxable_sale_extent="cannot_be_determined")
    values[THRESHOLD] = False
    qwen, cloud = envelopes(values)
    local = assess_response(json_text(qwen), SOURCE)
    invoice, _, review = assess(json_text(cloud), DOCUMENT)
    assert local.invoice.model_dump(mode="python") == invoice == values
    for issues in (local.review["issues"], review["issues"]):
        assert any(i["code"] == "threshold_inconsistent_not_corrected" for i in issues)


@pytest.mark.parametrize("reason", MISSING_REASONS)
def test_evaluation_requires_exact_reason_not_generic_absence(reason):
    reference = {"gst": reason}
    assert evaluate_fields(reference, {"gst": reason}, standard_version=SCHEMA_VERSION)["correct"] == 1
    for wrong in [None, "", reason.upper(), " " + reason] + [r for r in MISSING_REASONS if r != reason]:
        assert evaluate_fields(reference, {"gst": wrong}, standard_version=SCHEMA_VERSION)["incorrect"] == 1
    azure = {"gst": {"valueString": reason}}
    assert evaluate_fields(reference, azure, standard_version=SCHEMA_VERSION, prediction_format="azure")["correct"] == 1


def test_v3_evaluation_buyer_uses_ground_truth_gate_and_fraction_bounds():
    reference = {THRESHOLD: True, "buyer_identity": ""}
    prediction = {THRESHOLD: False, "buyer_identity": "not_found"}
    result = evaluate_fields(reference, prediction, standard_version=SCHEMA_VERSION)
    assert result["incorrect"] == 2
    assert evaluate_fields(reference, {THRESHOLD: True, "buyer_identity": ""}, standard_version=SCHEMA_VERSION)["correct"] == 2
    with pytest.raises(InputError):
        evaluate_fields({"taxable_sale_extent": 100}, {"taxable_sale_extent": 1}, standard_version=SCHEMA_VERSION)
    assert evaluate_fields({"taxable_sale_extent": 1}, {"taxable_sale_extent": 100}, standard_version=SCHEMA_VERSION)["incorrect"] == 1
    with pytest.raises(InputError):
        evaluate_fields({"gst": None}, {"gst": "not_found"}, standard_version=SCHEMA_VERSION)


def test_rules_baseline_keeps_legacy_null_and_percentage():
    assert TaxInvoice().gst is None
    assert TaxInvoice(taxable_sale_extent=100).taxable_sale_extent == 100
    assert evaluate_fields({"gst": None}, {"gst": None})["standard_version"] == "tirbic-15-v2"


@pytest.mark.parametrize("field", ["total_cost", "gst"])
@pytest.mark.parametrize("amount", ["51.10", "32.00", "0.00", "-32.00", "9999999999999999.99"])
def test_money_strings_survive_all_llm_contracts_and_serialization(field, amount):
    values = missing_invoice()
    values[field] = amount
    qwen, cloud = envelopes(values)
    local = assess_response(json_text(qwen), SOURCE)
    remote, validation, _ = assess(json_text(cloud), DOCUMENT)
    assert validation["valid"]
    for invoice in (local.invoice.model_dump(mode="python"), remote):
        assert json.loads(json_text(invoice))[field] == amount
    spec = invoice_schema()["properties"][field]["anyOf"][0]
    assert spec["type"] == "string" and "pattern" in spec


@pytest.mark.parametrize("field", ["total_cost", "gst"])
@pytest.mark.parametrize("amount", [51, Decimal("51.10"), True, "51.1", "32", "51.100",
                                   "$51.10", "AUD 51.10", "1,000.00", " 51.10", "51.10\n",
                                   "1e2", "NaN", "", "051.10", "10000000000000000.00"])
def test_noncanonical_money_is_rejected_without_silent_padding_or_rounding(field, amount):
    values = missing_invoice()
    values[field] = amount
    qwen, cloud = envelopes(values)
    invoice, validation, _ = assess(json_text(cloud), DOCUMENT)
    assert invoice is None and not validation["valid"]
    with pytest.raises(ExtractionError):
        assess_response(json_text(qwen), SOURCE)


def test_money_string_evidence_is_compared_numerically_but_not_rewritten():
    values = missing_invoice()
    values.update(total_cost="51.10", gst="0.00")
    values[THRESHOLD] = False
    qwen, cloud = envelopes(values)
    source = "Total $51.1 GST 0"
    qwen["evidence"].update(total_cost=["$51.1"], gst=["GST 0"])
    result = assess_response(json_text(qwen), source)
    assert result.invoice.total_cost == "51.10"
    assert result.review["fields"]["total_cost"]["value_supported"] is True
    assert result.review["fields"]["gst"]["value_supported"] is True
    _, _, review = assess(json_text(cloud), DOCUMENT)
    assert not any(i["code"] == "threshold_inconsistent_not_corrected" for i in review["issues"])
