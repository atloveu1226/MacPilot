from macpilot.phase3.resume_profile import parse_resume_profile


def test_readcv_output_supports_project_and_evidence_fields() -> None:
    profile = parse_resume_profile(
        {
            "basics": {
                "name": "Candidate",
                "target_role": "Backend Engineer",
                "links": ["https://github.com/example"],
            },
            "projects": [
                {
                    "name": "MacPilot",
                    "start_date": "2025-01",
                    "end_date": "进行中",
                    "role": "Developer",
                    "description": "A local-first agent",
                    "technologies": ["Python"],
                    "outcomes": ["Built a working prototype"],
                }
            ],
            "evidence": [
                {
                    "field": "projects[0].role",
                    "value": "Developer",
                    "source": "resume.pdf",
                    "location": "Projects section",
                    "confidence": 0.95,
                }
            ],
        }
    )

    assert profile.basics.target_role == "Backend Engineer"
    assert profile.projects[0].role == "Developer"
    assert profile.evidence[0].location == "Projects section"
