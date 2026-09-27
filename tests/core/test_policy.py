from macpilot.core.policy import requires_approval, risk_action


def test_deterministic_policy_cannot_be_downgraded_by_model_plan() -> None:
    plan = {
        "requires_approval": False,
        "steps": [{"id": "submit", "tool": "submit_form"}],
    }

    assert requires_approval("准备并提交申请", plan)
    assert risk_action("准备并提交申请", plan) == "submit_form"


def test_low_risk_research_plan_does_not_require_approval() -> None:
    plan = {
        "requires_approval": False,
        "steps": [{"id": "read", "tool": "read_file"}],
    }

    assert not requires_approval("总结本地资料", plan)
    assert risk_action("总结本地资料", plan) == "external_action"
