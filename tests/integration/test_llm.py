"""Real Qwen + synthetic OCR-text fixture. Does not claim image-to-JSON accuracy."""
from dataclasses import replace
from datetime import date
from decimal import Decimal
import os
import uuid

import pytest

from app.core.config import Settings
from app.core.files import contained, write_json
from app.llm.adapter import LocalLlmExtractor


@pytest.mark.integration
@pytest.mark.llm_integration
def test_real_qwen_synthetic_text():
    if os.environ.get("RUN_LLM_INTEGRATION") != "1":
        pytest.skip("Set RUN_LLM_INTEGRATION=1 with the pinned model and LLM environment")
    settings = replace(Settings.from_env(), extractor="llm")
    # Handwritten synthetic input: not real OCR or private invoice content.
    text = "SYNTHETIC TEST DOCUMENT\nTax Invoice\nSupplier: Example Test Services\nInvoice Number: SYN-004\nInvoice Date: 2026-08-27\nCurrency: AUD\nTotal: $110.00\nGST: $10.00\n"
    output = contained(settings.root, f".runtime/llm-integration-{uuid.uuid4().hex}", must_exist=False)
    output.mkdir(parents=True)
    # Retain the real model response even when validation/assertions fail.
    result = LocalLlmExtractor(settings).extract_to(text, output)
    write_json(output / "extracted.json", result.model_dump(mode="python"))
    assert result.total_cost == Decimal("110.00")
    assert result.gst == Decimal("10.00")
    assert result.document_number == "SYN-004"
    assert result.document_type == "tax_invoice"
    assert result.seller_business_name == "Example Test Services"
    assert result.date_of_issue == date(2026, 8, 27)
    assert result.is_total_cost_equal_to_or_higher_than_1000 is False
