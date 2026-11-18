def configurations(root, origin):
    target = root / "target.toml"
    target.write_text(
        '[target]\nname="fixture"\nmodel="fixture-target"\n'
        'secret_ref="env:PIPELINE_KEY"\n'
        f'base_url="{origin}/target"\n'
        "[limits]\nrequests_per_minute=10000\nrun_timeout_seconds=180\n"
        "request_timeout_seconds=10\n",
        encoding="utf-8",
    )
    evaluator = root / "evaluator.toml"
    evaluator.write_text(
        "\n".join(
            f'[roles.{role}]\nmodel="fixture-{role}"\nsecret_ref="env:PIPELINE_KEY"\n'
            f'base_url="{origin}/evaluator"\n'
            for role in ("selector", "generator", "judge", "reporter")
        ),
        encoding="utf-8",
    )
    return target, evaluator
