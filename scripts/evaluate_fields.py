"""Compare local field maps without running OCR or printing document values."""
import argparse
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import ROOT
from app.core.errors import PipelineError
from app.core.files import contained, new_run, read_json, sha256, write_json
from app.evaluation.fields import evaluate_fields


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", required=True, help="Repository-relative ground-truth field map")
    parser.add_argument("--predicted", required=True, help="Repository-relative prediction JSON")
    parser.add_argument("--prediction-format", choices=["plain", "azure"], default="plain")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    try:
        expected = contained(ROOT, args.expected)
        predicted = contained(ROOT, args.predicted)
        result = evaluate_fields(read_json(expected), read_json(predicted), prediction_format=args.prediction_format)
        run_id = args.run_id or "evaluation-" + uuid.uuid4().hex
        output = new_run(ROOT, run_id)
        write_json(output / "evaluation.json", result)
        write_json(output / "review.json", {
            "operation": "offline_field_evaluation", "schema_version": result["standard_version"],
            "reference_sha256": sha256(expected), "prediction_sha256": sha256(predicted),
            "evaluation_sha256": sha256(output / "evaluation.json"),
        })
        print(f"Evaluation saved: outputs/{run_id}/evaluation.json; correct={result['correct']}, evaluated={result['evaluated']}")
        return 0
    except (PipelineError, OSError, ValueError, TypeError):
        print("Evaluation failed; check local paths and field-map format", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
