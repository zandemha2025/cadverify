from src.services.batch_service import portfolio_verdict

def test_portfolio_pass_requires_every_part_complete_and_pass():
    assert portfolio_verdict({"pass": 3}, 3)["verdict"] == "pass"
    assert portfolio_verdict({"pass": 2}, 3)["verdict"] == "incomplete"

def test_portfolio_issues_and_fail_are_honest():
    assert portfolio_verdict({"pass": 2, "issues": 1}, 3)["verdict"] == "issues"
    assert portfolio_verdict({"pass": 2, "fail": 1}, 3)["verdict"] == "fail"
    assert portfolio_verdict({"pass": 2, "processing_failed": 1}, 3)["verdict"] == "fail"
