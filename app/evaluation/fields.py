"""Offline field comparison against the supplied labelling standard.

Reference is a plain field map: null explicitly means not found. Omitted
reference keys are unannotated, not missing ground truth. Azure predictions
must be a single field map (or a single {"fields": ...} object), not a batch.
"""
from datetime import date
from decimal import Decimal, InvalidOperation
import re

from app.core.errors import InputError
from app.extraction.invoice import parse_date
from app.schemas.invoice import TaxInvoice, SUPPLY_TYPES, EXPENSE_CATEGORIES
from app.schemas.tirbic_llm import MISSING_REASONS

FIELDS = tuple(TaxInvoice.model_fields)
BOOL_FIELDS = {"paid", "is_total_cost_equal_to_or_higher_than_1000"}
DATE_FIELDS = {"date_of_expense", "date_of_issue", "payment_due_date"}
NUMBER_FIELDS = {"total_cost", "gst", "taxable_sale_extent"}
INVALID = object()


def empty(value):
    # False and numeric zero are real values, not absence.
    return value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, (list, dict)) and not value)


def prediction_value(value, azure):
    if not azure:
        return value, value is None or (isinstance(value, str) and not value.strip()), False
    if value is None:
        return None, True, False
    if not isinstance(value, dict):
        return INVALID, False, False
    populated = [(k, v) for k, v in value.items() if k.startswith("value") and not empty(v)]
    has_source = not empty(value.get("source"))
    if not populated:
        return None, not has_source, has_source
    if len(populated) != 1 or populated[0][0] not in {"valueString", "valueNumber", "valueInteger", "valueBoolean", "valueDate"}:
        return INVALID, False, has_source
    return populated[0][1], False, has_source


def normalize(field, value, *, standard_version="tirbic-15-v2"):
    if value is INVALID or value is None:
        return INVALID
    if field == "document_type":
        if not isinstance(value, str):
            return INVALID
        value = re.sub(r"[\s_]", "", value).lower()
        return value if value in {"taxinvoice", "bill", "receipt", "customercopy", "invoice"} else INVALID
    if field in {"document_number", "seller_abn"}:
        if not isinstance(value, str):
            return INVALID
        value = re.sub(r"\s", "", value)
        if field == "seller_abn" and not re.fullmatch(r"[0-9]{11}", value):
            return INVALID
        return value if value else INVALID
    if field in BOOL_FIELDS:
        return value if isinstance(value, bool) else INVALID
    if field in DATE_FIELDS:
        if type(value) is date:
            return value
        return (parse_date(value) or INVALID) if isinstance(value, str) else INVALID
    if field in NUMBER_FIELDS:
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
            return INVALID
        text = str(value).strip()
        if field != "taxable_sale_extent":
            text = re.sub(r"^(?:AUD\s*)?(?:A?\$\s*)?", "", text, flags=re.I)
            text = re.sub(r"\s*AUD$", "", text, flags=re.I).strip()
        if not re.fullmatch(r"-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", text):
            return INVALID
        try:
            result = Decimal(text.replace(",", ""))
            maximum = 1 if standard_version == "tirbic-15-v3" else 100
            if not result.is_finite() or (field == "taxable_sale_extent" and not 0 <= result <= maximum):
                return INVALID
            return result
        except InvalidOperation:
            return INVALID
    if not isinstance(value, str):
        return INVALID
    if field == "supply_type" and value not in SUPPLY_TYPES:
        return INVALID
    if field == "expense_category" and value not in EXPENSE_CATEGORIES:
        return INVALID
    return value  # Names and classifications use exact matching, not fuzzy scores.


def evaluate_fields(reference: dict, prediction: dict, *, prediction_format: str = "plain",
                    standard_version: str = "tirbic-15-v2") -> dict:
    if standard_version not in {"tirbic-15-v2", "tirbic-15-v3"}:
        raise InputError("Unsupported evaluation standard")
    if prediction_format not in {"plain", "azure"}:
        raise InputError("Unsupported evaluation format")
    if not isinstance(reference, dict) or not isinstance(prediction, dict):
        raise InputError("Evaluation expects field maps")
    azure = prediction_format == "azure"
    if azure and "fields" in prediction:
        prediction = prediction["fields"]
    if not isinstance(prediction, dict) or set(reference) - set(FIELDS) or set(prediction) - set(FIELDS):
        raise InputError("Unknown fields or unsupported batch envelope")
    gate = reference.get("is_total_cost_equal_to_or_higher_than_1000")
    results = {}
    for field in FIELDS:
        if field == "buyer_identity" and gate is not True:
            results[field] = {"status": "not_applicable" if gate is False else "dependency_unknown"}
            continue
        if field not in reference:
            results[field] = {"status": "not_annotated"}
            continue
        expected = reference[field]
        value, missing, _ = prediction_value(prediction.get(field), azure)
        if standard_version == "tirbic-15-v3":
            if expected is None or (field == "buyer_identity" and expected == "not_found"):
                raise InputError("Invalid v3 ground-truth missing value")
            if isinstance(expected, str) and (expected in MISSING_REASONS or (field == "buyer_identity" and expected == "")):
                correct = field in prediction and type(value) is str and value == expected
                results[field] = {"status": "correct" if correct else "incorrect",
                                  "reason": "exact_missing_reason_match" if correct else "missing_reason_mismatch"}
                continue
            if isinstance(value, str) and value in MISSING_REASONS:
                value, missing = INVALID, False
        not_found = expected is None or (field == "buyer_identity" and expected == "")
        if not_found:
            correct = missing
            reason = "not_found" if correct else "unexpected_value_or_source"
        else:
            normal_expected = normalize(field, expected, standard_version=standard_version)
            if normal_expected is INVALID:
                raise InputError("Invalid ground-truth field value")
            normal_value = normalize(field, value, standard_version=standard_version)
            correct = not missing and normal_value is not INVALID and normal_value == normal_expected
            reason = "match" if correct else "missing_or_mismatched_value"
        results[field] = {"status": "correct" if correct else "incorrect", "reason": reason}
    correct = sum(r["status"] == "correct" for r in results.values())
    incorrect = sum(r["status"] == "incorrect" for r in results.values())
    return {"standard_version": standard_version, "prediction_format": prediction_format,
            "fields": results, "correct": correct, "incorrect": incorrect,
            "evaluated": correct + incorrect, "skipped": len(results) - correct - incorrect}
