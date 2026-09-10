"""Creating a session on a compiled circuit, and every refusal that guards it.

A16-8 resolves track, event and conditions identity before the runtime exists,
and refuses a package below the readiness rung. Its handoff records that it
added no tests for any of it. These drills create real sessions through the
real route and check the two halves that matter:

* **what a session proves.** The manifest, the snapshot and the persisted row
  all carry the same package hash, and that hash is the one the catalogue
  reports for the circuit. If they can disagree, none of them is evidence.
* **what a session refuses, and how.** An unknown circuit, an event held at a
  different circuit, a conditions tape with no frozen file, a package below
  ``geometry_validated`` and a tampered package are five different operator
  problems, so they are five different refusals rather than one generic one.

The packages are synthetic analytic loops written under registry ids. See
``conftest.py``: nothing here is a claim about a real circuit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from afterlap_core.tracks import ReadinessStatus

from .conftest import (
    ABSENT_TRACK,
    DISCOVERED_TRACK,
    REJECTED_TRACK,
    UNREGISTERED_TRACK,
    VALIDATED_TRACK,
    create_session,
    package_document_path,
    track_summary,
)

if TYPE_CHECKING:
    from afterlap_core.paths import Paths

SYNTHETIC_SKETCH_TRACK = "test-loop"
"""The scenario's own track: a `configs/tracks` sketch, not a compiled package."""


def _error(response) -> dict:  # type: ignore[no-untyped-def]
    return response.json()["error"]


def test_a_session_on_a_compiled_circuit_carries_the_catalogue_hash(client):
    created = create_session(client, track_id=VALIDATED_TRACK, idempotency_key="circuit-valid")
    assert created.status_code == 201, created.text
    body = created.json()
    manifest = body["manifest"]
    catalogued = track_summary(client.get("/api/v1/tracks").json(), VALIDATED_TRACK)
    print(f"\nsession {manifest['id']} on {manifest['track_id']} @ {manifest['track_package_hash']}")

    assert manifest["track_id"] == VALIDATED_TRACK
    assert manifest["track_package_hash"] == catalogued["package_hash"], (
        "the hash a session recorded is not the hash the catalogue reports for that circuit, so "
        "neither proves which geometry ran"
    )
    assert manifest["track_readiness"] == ReadinessStatus.GEOMETRY_VALIDATED.value
    assert manifest["geometry_provenance"] == catalogued["geometry_provenance"]

    fetched = client.get(f"/api/v1/sessions/{manifest['id']}/snapshot").json()
    assert fetched["manifest"]["track_package_hash"] == manifest["track_package_hash"]
    assert fetched["capabilities"]["track_geometry"] == "available", (
        "a session on an independently validated package reported its geometry as anything but "
        f"available: {fetched['capabilities']['track_geometry']}"
    )


def test_a_real_circuit_session_is_labelled_and_says_what_it_does_not_claim(client):
    created = create_session(client, track_id=VALIDATED_TRACK, idempotency_key="circuit-label")
    assert created.status_code == 201, created.text
    sources = created.json()["manifest"]["source_capabilities"]
    limitations = [note for capability in sources for note in capability["limitations"]]
    print(f"\nlimitations: {[note[:70] for note in limitations]}")

    assert any("real_circuit_synthetic_energy" in note for note in limitations), (
        "a session on compiled geometry with synthetic car and battery parameters did not carry "
        "the label that says so"
    )
    assert any("corridor_quality=unknown" in note for note in limitations), (
        "the package has no usable corridor and the session made no note of the lateral claim it "
        "is therefore not making"
    )


def test_a_synthetic_sketch_session_makes_no_real_circuit_claim(client):
    """The pre-A16 path still works and still says it is a sketch."""
    created = create_session(client, idempotency_key="circuit-sketch")
    assert created.status_code == 201, created.text
    manifest = created.json()["manifest"]

    assert manifest["track_id"] == SYNTHETIC_SKETCH_TRACK
    assert manifest["track_package_hash"] is None, "a synthetic sketch produced a package hash"
    assert manifest["track_readiness"] is None

    limitations = [
        note
        for capability in created.json()["manifest"]["source_capabilities"]
        for note in capability["limitations"]
    ]
    assert any("synthetic sketch" in note for note in limitations)
    assert not any("real_circuit_synthetic_energy" in note for note in limitations)


def test_an_unknown_circuit_is_refused_by_name_with_what_exists(client):
    response = create_session(client, track_id="nurburgring", idempotency_key="circuit-unknown")
    assert response.status_code == 404, response.text
    error = _error(response)
    print(f"\n{error['message']}")
    assert error["code"] == "not_found"
    assert VALIDATED_TRACK in error["details"]["available_tracks"]
    assert "/private/" not in error["message"] and "/Users/" not in error["message"]


def test_a_circuit_below_the_readiness_rung_is_refused_with_the_rung_it_holds(client):
    response = create_session(client, track_id=DISCOVERED_TRACK, idempotency_key="circuit-discovered")
    assert response.status_code == 422, response.text
    error = _error(response)
    print(f"\n{error['message']}")
    assert error["code"] == "validation_failed"
    assert error["details"]["track_readiness"] == ReadinessStatus.DISCOVERED.value
    assert error["details"]["required_readiness"] == ReadinessStatus.GEOMETRY_VALIDATED.value


def test_a_rejected_package_is_refused_rather_than_treated_as_untested(client):
    response = create_session(client, track_id=REJECTED_TRACK, idempotency_key="circuit-rejected")
    assert response.status_code == 422, response.text
    assert _error(response)["details"]["track_readiness"] == ReadinessStatus.REJECTED.value


def test_a_circuit_with_no_compiled_package_is_refused_not_defaulted(client):
    response = create_session(client, track_id=ABSENT_TRACK, idempotency_key="circuit-absent")
    assert response.status_code == 404, response.text
    assert ABSENT_TRACK in _error(response)["message"]


def test_a_tampered_package_cannot_start_a_session(client, catalogue_paths: Paths):
    """The loader's hash check is what stands between a session and edited geometry."""
    document = package_document_path(catalogue_paths, VALIDATED_TRACK)
    document.write_text(document.read_text(encoding="utf-8").replace("4000.0", "4100.0", 1), encoding="utf-8")

    response = create_session(client, track_id=VALIDATED_TRACK, idempotency_key="circuit-tampered")
    print(f"\n{_error(response)['message']}")
    assert response.status_code == 404, response.text
    assert "hash verification" in _error(response)["message"]


def test_an_event_held_at_a_different_circuit_is_refused(client):
    """Calendar event and physical circuit are separate identities."""
    listing = client.get("/api/v1/tracks").json()
    elsewhere = next(
        entry for entry in listing["tracks"] if entry["track_id"] != VALIDATED_TRACK and entry["event_ids"]
    )
    foreign_event = elsewhere["event_ids"][0]

    response = create_session(
        client,
        track_id=VALIDATED_TRACK,
        event_id=foreign_event,
        idempotency_key="circuit-wrong-event",
    )
    assert response.status_code == 422, response.text
    error = _error(response)
    print(f"\n{error['message']}")
    assert error["details"]["event_track_id"] == elsewhere["track_id"]
    assert error["details"]["track_id"] == VALIDATED_TRACK


def test_an_unknown_event_is_refused_with_the_events_that_exist(client):
    response = create_session(
        client,
        track_id=VALIDATED_TRACK,
        event_id="grand-prix-of-nowhere",
        idempotency_key="circuit-unknown-event",
    )
    assert response.status_code == 404, response.text
    assert "registry" in _error(response)["message"]


def test_an_event_cannot_be_applied_to_a_synthetic_sketch(client):
    listing = client.get("/api/v1/tracks").json()
    any_event = next(e["event_ids"][0] for e in listing["tracks"] if e["event_ids"])

    response = create_session(client, event_id=any_event, idempotency_key="circuit-sketch-event")
    assert response.status_code == 422, response.text
    assert "synthetic sketch" in _error(response)["message"]


def test_conditions_with_no_frozen_tape_are_refused_rather_than_fetched(client):
    """A session request must never depend on when it was made.

    The artefact tree here holds no frozen tapes, so this is the real offline
    refusal rather than a patched one: fetching weather while an operator waits
    would make the session's identity depend on the network.
    """
    available = client.get("/api/v1/conditions").json()["conditions"]
    unavailable = next(entry["conditions_id"] for entry in available if not entry["available"])

    response = create_session(
        client,
        track_id=VALIDATED_TRACK,
        conditions_id=unavailable,
        idempotency_key="circuit-conditions",
    )
    assert response.status_code == 503, response.text
    error = _error(response)
    print(f"\n{error['message']}")
    assert error["code"] == "capability_unavailable"
    assert error["details"]["conditions_id"] == unavailable
    assert "/private/" not in error["message"] and "/Users/" not in error["message"]


def test_an_unknown_conditions_id_is_refused_with_what_exists(client):
    response = create_session(
        client,
        track_id=VALIDATED_TRACK,
        conditions_id="tuesday-drizzle",
        idempotency_key="circuit-bad-conditions",
    )
    assert response.status_code == 404, response.text
    assert _error(response)["details"]["available_conditions"]


def test_a_circuit_outside_the_registry_can_still_start_a_session(client):
    """Member 1's packages arrive before their registry entries sometimes.

    Compiled and validated is what a session needs; being in the calendar is a
    separate fact. Nothing in the factory is keyed on a registry id, and this
    is the drill that notices if something becomes so.
    """
    created = create_session(client, track_id=UNREGISTERED_TRACK, idempotency_key="circuit-unregistered")
    assert created.status_code == 201, created.text
    manifest = created.json()["manifest"]
    assert manifest["track_id"] == UNREGISTERED_TRACK
    assert manifest["track_package_hash"]


def test_a_scenario_whose_checkpoints_the_circuit_lacks_is_refused(client, catalogue_paths: Paths):
    """A session that could not be evaluated is refused, not silently run.

    The compiled circuit is rewritten without the corners the scenario
    evaluates, so its checkpoints genuinely do not exist on it.
    """
    from .conftest import analytic_loop, build_package, write_package

    package = build_package(VALIDATED_TRACK)
    stripped = package.model_copy(update={"features": package.features.model_copy(update={"corners": ()})})
    write_package(catalogue_paths, stripped, analytic_loop())

    response = create_session(client, track_id=VALIDATED_TRACK, idempotency_key="circuit-no-cp")
    assert response.status_code == 422, response.text
    error = _error(response)
    print(f"\n{error['message']}")
    assert "attack-exit" in error["message"]
    assert error["details"]["track_id"] == VALIDATED_TRACK
