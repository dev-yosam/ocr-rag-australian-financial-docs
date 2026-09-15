import os
import uuid
from decimal import Decimal

import pytest

from app.core.config import ROOT, Settings
from app.core.files import json_text, read_json
from app.pipeline import InvoicePipeline
from app.rag.client import RagFlowClient


@pytest.mark.integration
@pytest.mark.paddleocr_integration
def test_real_vl16_invoice():
    if os.environ.get("RUN_PADDLEOCR_INTEGRATION") != "1":
        pytest.skip("Set RUN_PADDLEOCR_INTEGRATION=1 after explicit model preparation")
    result = InvoicePipeline(Settings.from_env()).process("samples/tax_invoices/sample_invoice.png", "integration-" + uuid.uuid4().hex)
    expected = read_json(ROOT / "samples/tax_invoices/expected.json")
    import simplejson
    assert simplejson.loads(json_text(result["invoice"]), use_decimal=True) == expected
    manifest = read_json(ROOT / "outputs" / result["run_id"] / "manifest.json")
    assert manifest["versions"]["pipeline"] == "PaddleOCR-VL-1.6"


@pytest.mark.integration
@pytest.mark.ragflow_integration
def test_self_hosted_ragflow_upload():
    if os.environ.get("RUN_RAGFLOW_INTEGRATION") != "1":
        pytest.skip("Set RUN_RAGFLOW_INTEGRATION=1 with a self-hosted synthetic test dataset")
    settings = Settings.from_env()
    client = RagFlowClient(settings.ragflow_base_url, settings.ragflow_api_key)
    try:
        document_id = client.upload_markdown(settings.ragflow_dataset_id,
            f"synthetic-integration-{uuid.uuid4().hex}.md", b"SYNTHETIC - NOT VALID FOR PAYMENT\nTotal: AUD 110.00")
        client.start_parsing(settings.ragflow_dataset_id, document_id)
        assert client.get_status(settings.ragflow_dataset_id, document_id) in {"uploaded", "processing", "completed"}
    finally:
        client.close()
