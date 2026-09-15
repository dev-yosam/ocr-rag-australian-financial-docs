import argparse
import sys

from app.core.config import Settings
from app.core.errors import PipelineError
from app.pipeline import InvoicePipeline
from app.rag.artifacts import prepare, submit
from app.rag.client import RagFlowClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local synthetic invoice processing")
    commands = parser.add_subparsers(dest="command", required=True)
    process = commands.add_parser("process")
    process.add_argument("source")
    process.add_argument("--run-id")
    rag = commands.add_parser("rag").add_subparsers(dest="action", required=True)
    for action in ("prepare", "submit"):
        rag.add_parser(action).add_argument("directory")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        if args.command == "process":
            result = InvoicePipeline(settings).process(args.source, args.run_id)
            print(f"Completed run: {result['run_id']}; artifacts saved locally")
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
    except (PipelineError, OSError):
        print("Operation failed; inspect local artifacts and documented prerequisites", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
