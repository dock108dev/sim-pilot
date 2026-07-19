from sim_pilot.domain.world import FieldChanged
from sim_pilot.openttd.query_output import render_table, render_world_changes


def test_render_table_reports_empty_collections() -> None:
    assert render_table(("ID",), ()) == "No records."


def test_render_world_changes_exposes_before_and_after_values() -> None:
    rendered = render_world_changes(
        (
            FieldChanged(
                entity_type="company",
                entity_id="company:opaque-identifier",
                field="cash",
                before=100,
                after=200,
            ),
        )
    )

    assert "field_changed" in rendered
    assert "cash" in rendered
    assert "100" in rendered
    assert "200" in rendered
