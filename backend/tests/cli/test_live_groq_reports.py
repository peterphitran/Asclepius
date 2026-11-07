import html

import pytest

from asclepius.exports import render_report
from scripts.live_groq_fixture import redact
from tests.cli.test_results import evidence_view


@pytest.mark.parametrize("format", ("json", "markdown", "html"))
def test_rendered_report_redacts_reflected_key_and_preserves_other_evidence(format):
    secret = 'ab"cd'
    view = evidence_view()
    observations = list(view.observations)
    reflected = html.escape(secret)
    original = observations[0]
    observations[0] = original.model_copy(
        update={
            "payload": original.payload.model_copy(
                update={"content": f"provider says {reflected}; keep public detail"}
            )
        }
    )
    case_distinct = observations[1]
    observations[1] = case_distinct.model_copy(
        update={
            "payload": case_distinct.payload.model_copy(
                update={"content": 'provider says AB"CD; keep separate detail'}
            )
        }
    )
    view = view.model_copy(update={"observations": tuple(observations)})

    output = redact(render_report(view, format).content, (secret,))
    decoded = html.unescape(html.unescape(output)).replace(r"\"", '"')

    assert secret not in decoded
    assert "[REDACTED]" in output
    assert "keep public detail" in decoded
    assert 'AB"CD; keep separate detail' in decoded
