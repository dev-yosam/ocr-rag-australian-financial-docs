from app import cli
from app.core.config import Settings
from app.pipeline import InvoicePipeline


def test_cli_common_pipeline_and_safe_output(repo, fake_parser, monkeypatch, capsys):
    service = InvoicePipeline(Settings(root=repo), fake_parser)
    monkeypatch.setattr(cli.Settings, "from_env", lambda: Settings(root=repo))
    monkeypatch.setattr(cli, "InvoicePipeline", lambda settings: service)
    assert cli.main(["process", "invoice.png", "--run-id", "cli-test"]) == 0
    assert "Example Synthetic" not in capsys.readouterr().out
    assert cli.main(["rag", "prepare", "outputs/cli-test"]) == 0
    assert cli.main(["process", "../outside"]) == 1


def test_timeout_process_terminates(repo):
    import sys
    from app.paddleocr.adapter import execute_worker
    result = execute_worker([sys.executable, "-c", "import time; time.sleep(30)"], repo, 0.2)
    assert result.termination == "timeout"
    assert result.returncode != 0
