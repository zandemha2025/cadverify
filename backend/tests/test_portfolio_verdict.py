from src.services.batch_service import portfolio_verdict

def test_portfolio_pass_requires_every_part_complete_and_pass():
    assert portfolio_verdict({"pass": 3}, 3)["verdict"] == "pass"
    assert portfolio_verdict({"pass": 2}, 3)["verdict"] == "incomplete"

def test_portfolio_issues_and_fail_are_honest():
    assert portfolio_verdict({"pass": 2, "issues": 1}, 3)["verdict"] == "issues"
    assert portfolio_verdict({"pass": 2, "fail": 1}, 3)["verdict"] == "fail"
    assert portfolio_verdict({"pass": 2, "processing_failed": 1}, 3)["verdict"] == "fail"

def test_portfolio_keeps_skipped_items_visible_and_terminal():
    result = portfolio_verdict({"skipped": 3}, 3)
    assert result["verdict"] == "fail"
    assert result["skipped_items"] == 3
    assert result["completed_items"] == 0
