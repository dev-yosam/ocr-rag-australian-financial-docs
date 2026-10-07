import argparse
import sys
from dataclasses import replace

from app.core.config import ROOT, Settings
from app.core.errors import PipelineError
from app.pipeline import InvoicePipeline
from app.ocr_pipeline import OcrPipeline
from app.rag.artifacts import prepare, submit
from app.rag.client import RagFlowClient


def _print_extraction_result(result: dict, *, reused_ocr: bool = False) -> None:
    # Only report metadata: receipt text and model quotations stay in artifacts.
    print(f"處理完成：{result['run_id']}；狀態：{result['status']}")
    if reused_ocr:
        print("已重用既有 OCR 結果，未重新辨識圖片。")
    if result["requires_review"]:
        fields = ", ".join(result["review"]["fields_requiring_review"])
        print(f"需要人工確認的欄位：{fields}")
        print(f"欄位值已保留；檢查說明：{result['artifacts']['review.json']}")
    elif result["review"] is not None:
        print("格式驗證通過，未發現來源檢查問題；不代表內容已確認正確。")
    print(f"結果：{result['artifacts']['extracted.json']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local synthetic invoice processing")
    commands = parser.add_subparsers(dest="command", required=True)
    parse = commands.add_parser("parse", help="Parse one document with OCR only; no field extraction")
    parse.add_argument("source")
    parse.add_argument("--run-id")
    process = commands.add_parser("process")
    process.add_argument("source")
    process.add_argument("--run-id")
    process.add_argument("--extractor", choices=("rules", "llm"))
    extract = commands.add_parser("extract", help="Re-extract a previous run without rerunning OCR")
    extract.add_argument("directory")
    extract.add_argument("--run-id")
    extract.add_argument("--extractor", choices=("rules", "llm", "gemini", "openai"))
    extract.add_argument("--dry-run", action="store_true", help="Gemini only: save request locally without contacting Google")
    rag = commands.add_parser("rag").add_subparsers(dest="action", required=True)
    for action in ("prepare", "submit"):
        rag.add_parser(action).add_argument("directory")
    args = parser.parse_args(argv)
    try:
        if getattr(args, "dry_run", False) and args.extractor != "gemini":
            raise PipelineError("--dry-run requires --extractor gemini")
        if args.command == "extract" and args.extractor == "openai":
            from app.openai_extraction.config import OpenAISettings
            from app.openai_extraction.pipeline import OpenAIPipeline
            settings = OpenAISettings.from_env()
            print(f"OpenAI model: {settings.model}")
            result = OpenAIPipeline(ROOT, settings).reextract(args.directory, args.run_id)
            print(f"OpenAI：{result['status']}；run_id：{result['run_id']}")
            print("已重用 OCR 區塊並送至 OpenAI；未重跑 OCR。格式通過不代表內容正確，請查看 review.json。")
            for name, path in result["artifacts"].items():
                print(f"{name}：{path}")
            return 0
        if args.command == "extract" and args.extractor == "gemini":
            from app.gemini.config import GeminiSettings
            from app.gemini.pipeline import GeminiPipeline
            settings = GeminiSettings.from_env(require_key=not args.dry_run)
            result = GeminiPipeline(ROOT, settings).reextract(args.directory, args.run_id, dry_run=args.dry_run)
            print(f"Gemini：{result['status']}；run_id：{result['run_id']}")
            print("僅準備本機請求，未連線。" if args.dry_run else "已送出 OCR 區塊至 Google；格式通過不代表內容正確，請查看 review.json。")
            for name, path in result["artifacts"].items():
                print(f"{name}：{path}")
            return 0
        settings = Settings.from_ocr_env() if args.command == "parse" else Settings.from_env()
        if getattr(args, "extractor", None):
            settings = replace(settings, extractor=args.extractor)
        if args.command == "parse":
            result = OcrPipeline(settings).parse(args.source, args.run_id)
            print(f"OCR 完成：{result['run_id']}；狀態：{result['ocr_status']}；頁數：{result['page_count']}")
            print("未執行欄位抽取；OCR 完成不代表內容已確認正確。")
            for name, path in result["artifacts"].items():
                print(f"{name}：{path}")
        elif args.command == "process":
            result = InvoicePipeline(settings).process(args.source, args.run_id)
            _print_extraction_result(result)
        elif args.command == "extract":
            result = InvoicePipeline(settings).reextract(args.directory, args.run_id)
            _print_extraction_result(result, reused_ocr=True)
        elif args.action == "prepare":
            prepare(settings.root, args.directory)
            print("RAGFlow preparation saved locally; no network request made")
        else:
            client = RagFlowClient(settings.ragflow_base_url, settings.ragflow_api_key,
                                   timeout=settings.ragflow_timeout)
            try:
                result = submit(settings, args.directory, client)
                print(f"RAGFlow status: {result['status']}")
            finally:
                client.close()
        return 0
    except (PipelineError, OSError) as exc:
        if args.command == "extract" and args.extractor in ("gemini", "openai") and isinstance(exc, PipelineError):
            print(str(exc), file=sys.stderr)
            return 1
        print("Operation failed; inspect local artifacts and documented prerequisites", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
