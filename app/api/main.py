from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict
from fastapi.exceptions import RequestValidationError

from app.core.config import Settings
from app.core.errors import InputError, PipelineError
from app.core.files import json_text
from app.pipeline import InvoicePipeline


class ProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str


def create_app(pipeline: InvoicePipeline | None = None) -> FastAPI:
    service = pipeline or InvoicePipeline(Settings.from_env())
    api = FastAPI(title="Australian Invoice M1")

    @api.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return Response(json_text({"error": "Invalid request"}), status_code=422, media_type="application/json")

    @api.exception_handler(PipelineError)
    async def pipeline_error(request, error):
        status = 400 if isinstance(error, InputError) else 503
        return Response(json_text({"error": str(error)}), status_code=status, media_type="application/json")

    @api.get("/health")
    def health():
        return {"status": "ok", "ocr_readiness": "not_checked"}

    @api.post("/v1/invoices/process")
    def process(request: ProcessRequest):
        result = service.process(request.source)
        return Response(json_text(result), media_type="application/json")

    return api


app = create_app()
