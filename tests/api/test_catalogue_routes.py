"""The read-only circuit catalogue, against a real artefact tree.

A16-8 shipped these routes and its handoff records that it added no tests. The
claims that most need holding are the ones a passing build would not otherwise
notice:

* every registry circuit appears, including the ones with nothing compiled. A
  circuit that is silently omitted looks exactly like one that is ready;
* readiness comes from the package's validation report, and only
  ``geometry_validated`` or above reports ``simulation_ready``;
* a tampered or malformed package is listed with its refusal reason rather
  than dropped or served;
* nothing is keyed on a circuit id: a compiled package the registry has never
  heard of is served the same way, because Member 1's 23 packages have to land
  without a code change;
* what reaches the wire is evidence — source URLs, licences, hashes, refusal
  reasons — and never a path on the server's disk.

Every package under test is a synthetic analytic loop written under a registry
id. See ``conftest.py``: nothing here is a claim about a real circuit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from afterlap_core.tracks import ReadinessStatus

from .conftest import (
    ABSENT_TRACK,
    DISCOVERED_TRACK,
    FIXTURE_LENGTH_M,
    FIXTURE_LICENCE,
    REJECTED_TRACK,
    UNREGISTERED_TRACK,
    VALIDATED_TRACK,
    analytic_loop,
    build_package,
    package_document_path,
    track_summary,
    write_package,
)

if TYPE_CHECKING:
    from afterlap_core.paths import Paths

REGISTRY_CIRCUIT_COUNT = 23


def test_the_listing_carries_every_registry_circuit_whether_compiled_or_not(client):
    body = client.get("/api/v1/tracks").json()
    listed = {entry["track_id"] for entry in body["tracks"]}
    print(f"\n{len(listed)} circuits listed, {sum(e['package_present'] for e in body['tracks'])} compiled")

    assert body["season"] == 2026
    assert body["minimum_readiness_to_drive"] == ReadinessStatus.GEOMETRY_VALIDATED.value
    assert len(listed) >= REGISTRY_CIRCUIT_COUNT, (
        f"the 2026 registry holds {REGISTRY_CIRCUIT_COUNT} circuits and the catalogue listed "
        f"{len(listed)}; an omitted circuit is indistinguishable from a ready one"
    )
    assert UNREGISTERED_TRACK in listed, (
        "a compiled package outside the registry vanished from the catalogue, so a circuit "
        "compiled before its registry entry lands would be invisible"
    )


def test_a_registry_circuit_with_nothing_compiled_reports_nulls_and_says_why(client):
    absent = track_summary(client.get("/api/v1/tracks").json(), ABSENT_TRACK)
    print(f"\n{ABSENT_TRACK}: {absent['notes']}")

    assert absent["package_present"] is False
    assert absent["package_hash"] is None
    assert absent["readiness"] is None
    assert absent["simulation_ready"] is False
    assert absent["unavailable_reason"] is None, (
        "an uncompiled circuit is not a failure to load one; the two need different reasons"
    )
    assert absent["notes"], "nothing explains why the hashes are null"
    assert absent["registry_readiness"] is not None, "the registry rung was dropped with the package"


def test_readiness_comes_from_the_validation_report_not_from_being_compiled(client):
    body = client.get("/api/v1/tracks").json()
    states = {
        entry["track_id"]: (entry["readiness"], entry["simulation_ready"])
        for entry in body["tracks"]
        if entry["package_present"]
    }
    print(f"\ncompiled states: {states}")

    assert states[VALIDATED_TRACK] == (ReadinessStatus.GEOMETRY_VALIDATED.value, True)
    assert states[DISCOVERED_TRACK] == (ReadinessStatus.DISCOVERED.value, False)
    assert states[REJECTED_TRACK] == (ReadinessStatus.REJECTED.value, False)


def test_a_detail_response_carries_the_evidence_and_no_server_path(client):
    body = client.get(f"/api/v1/tracks/{VALIDATED_TRACK}").json()
    print(f"\nsources: {[(s['source_id'], s['permission']) for s in body['sources']]}")

    assert body["track"]["package_hash"], "the detail response proves nothing without a hash"
    assert body["validation"]["status"] == ReadinessStatus.GEOMETRY_VALIDATED.value
    assert body["features"]["sector_count"] == 3
    assert "attack-exit" in body["features"]["corner_ids"]

    source = body["sources"][0]
    assert source["url"], "a source without its URL cannot be checked"
    assert source["permission"] == FIXTURE_LICENCE

    serialised = client.get(f"/api/v1/tracks/{VALIDATED_TRACK}").text
    assert "/private/" not in serialised and "/Users/" not in serialised, (
        "the detail response names a path on the server's disk"
    )
    assert not str(body["validation"]["report_path"] or "").startswith("/")


def test_an_unknown_circuit_is_a_typed_refusal_naming_what_exists(client):
    response = client.get("/api/v1/tracks/nurburgring-nordschleife")
    assert response.status_code == 404, response.text
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert VALIDATED_TRACK in error["details"]["available_tracks"]


def test_a_tampered_package_is_listed_with_its_refusal_rather_than_served(client, catalogue_paths: Paths):
    """A package whose document no longer hashes to what it declares.

    Edited in place, so the stored ``package_hash`` really disagrees with the
    document's contents. The circuit must still appear -- dropping it would
    read as "not compiled yet" -- and must not be reported as drivable.
    """
    document = package_document_path(catalogue_paths, VALIDATED_TRACK)
    document.write_text(
        document.read_text(encoding="utf-8").replace('"4000.0"', '"4100.0"').replace("4000.0", "4100.0", 1),
        encoding="utf-8",
    )

    summary = track_summary(client.get("/api/v1/tracks").json(), VALIDATED_TRACK)
    print(f"\ntampered: {summary['unavailable_reason']}")

    assert summary["package_present"] is False
    assert summary["simulation_ready"] is False
    assert summary["unavailable_reason"] is not None
    assert "hash verification" in summary["unavailable_reason"]
    assert "/private/" not in summary["unavailable_reason"]

    centreline = client.get(f"/api/v1/tracks/{VALIDATED_TRACK}/centreline")
    assert centreline.status_code == 404, centreline.text


def test_a_malformed_package_document_is_listed_with_its_parse_failure(client, catalogue_paths: Paths):
    package_document_path(catalogue_paths, VALIDATED_TRACK).write_text("{ not json", encoding="utf-8")
    summary = track_summary(client.get("/api/v1/tracks").json(), VALIDATED_TRACK)
    print(f"\nmalformed: {summary['unavailable_reason']}")

    assert summary["package_present"] is False
    assert summary["unavailable_reason"] is not None
    assert summary["registry_readiness"] is not None, "the registry identity went with the package"


def test_the_centreline_repeats_the_hashes_that_pin_the_arrays_it_came_from(client):
    body = client.get(f"/api/v1/tracks/{VALIDATED_TRACK}/centreline", params={"stride_m": 100.0}).json()
    listing = track_summary(client.get("/api/v1/tracks").json(), VALIDATED_TRACK)
    print(f"\n{body['point_count']} points at {body['stride_m']} m from {body['source_point_count']}")

    assert body["package_hash"] == listing["package_hash"], (
        "the geometry a consumer plots is not provably the geometry the catalogue described"
    )
    assert body["arrays_sha256"] == listing["arrays_sha256"]
    assert body["length_m"] == FIXTURE_LENGTH_M
    assert body["index_stride"] == 100
    assert len(body["s_m"]) == body["point_count"] == 40
    assert len(body["x_m"]) == len(body["y_m"]) == len(body["curvature_1pm"]) == body["point_count"]
    assert body["units"]["s_m"] == "m"


def test_a_stride_that_would_return_a_dense_lap_is_refused_not_truncated(client, catalogue_paths: Paths):
    """A silently coarsened lap would misrepresent the geometry it came from."""
    long_id = "synthetic-long-fixture"
    centreline = analytic_loop(25000.0)
    write_package(catalogue_paths, build_package(long_id, centreline=centreline), centreline)

    response = client.get(f"/api/v1/tracks/{long_id}/centreline", params={"stride_m": 1.0})
    assert response.status_code == 422, response.text
    message = response.json()["error"]["message"]
    print(f"\nrefused: {message}")
    assert "coarser stride" in message

    coarse = client.get(f"/api/v1/tracks/{long_id}/centreline", params={"stride_m": 25.0})
    assert coarse.status_code == 200, coarse.text
    assert coarse.json()["point_count"] == 1000


def test_a_circuit_with_no_compiled_arrays_refuses_the_centreline_by_name(client):
    response = client.get(f"/api/v1/tracks/{DISCOVERED_TRACK}/centreline")
    assert response.status_code == 404, response.text
    assert DISCOVERED_TRACK in response.json()["error"]["message"]


def test_a_package_outside_the_registry_is_served_the_same_way(client):
    """Member 1's packages must land without a code change here.

    Nothing in the route is keyed on a circuit id, and this is the drill that
    would notice if something became so: an id the registry has never seen is
    compiled, listed, detailed and plotted exactly like a registry circuit.
    """
    summary = track_summary(client.get("/api/v1/tracks").json(), UNREGISTERED_TRACK)
    assert summary["package_present"] is True
    assert summary["simulation_ready"] is True
    assert summary["registry_readiness"] is None, "an unregistered circuit gained a registry rung"

    detail = client.get(f"/api/v1/tracks/{UNREGISTERED_TRACK}")
    assert detail.status_code == 200, detail.text
    centreline = client.get(f"/api/v1/tracks/{UNREGISTERED_TRACK}/centreline")
    assert centreline.status_code == 200, centreline.text


def test_a_circuit_compiled_after_startup_appears_without_a_restart(client, catalogue_paths: Paths):
    """The catalogue reads the tree, it does not cache a snapshot of it."""
    assert track_summary(client.get("/api/v1/tracks").json(), ABSENT_TRACK)["package_present"] is False

    write_package(catalogue_paths, build_package(ABSENT_TRACK))

    refreshed = track_summary(client.get("/api/v1/tracks").json(), ABSENT_TRACK)
    print(f"\n{ABSENT_TRACK} after compiling: {refreshed['readiness']}")
    assert refreshed["package_present"] is True
    assert refreshed["simulation_ready"] is True


def test_the_conditions_catalogue_resolves_offline_and_names_absent_tapes(client):
    body = client.get("/api/v1/conditions").json()
    by_id = {entry["conditions_id"]: entry for entry in body["conditions"]}
    print(f"\nconditions: {[(k, v['available']) for k, v in by_id.items()]}")

    assert by_id, "no conditions documents were listed at all"
    assert "network" in body["notice"] or "offline" in body["notice"]

    for entry in by_id.values():
        assert "frozen_tape_path" not in entry, "the response names the server's cache path"
        assert isinstance(entry["frozen_tape_available"], bool)
        if not entry["available"]:
            assert entry["unavailable_reason"], "an unavailable tape does not say why"
            assert "/private/" not in entry["unavailable_reason"]
            assert "/Users/" not in entry["unavailable_reason"]


def test_the_scenario_catalogue_resolves_the_circuit_each_scenario_would_run_on(client):
    body = client.get("/api/v1/scenarios").json()
    by_id = {entry["scenario_id"]: entry for entry in body["scenarios"]}
    print(f"\nscenarios: {[(k, v['real_circuit'], v['track_readiness']) for k, v in by_id.items()]}")

    assert by_id, "no scenario documents were listed"
    for entry in by_id.values():
        if entry["track_id"] == DISCOVERED_TRACK:
            assert entry["unavailable_reason"], (
                "a scenario on a circuit below the readiness rung offered a session that would be refused"
            )
            assert ReadinessStatus.DISCOVERED.value in entry["unavailable_reason"]
        if entry["real_circuit"]:
            assert entry["track_package_hash"], "a real-circuit scenario carries no package hash"
            assert entry["run_label"] == "real_circuit_synthetic_energy"


def test_every_catalogue_route_lives_under_one_api_prefix(client):
    """One authoritative prefix. A second surface is a second thing to keep true."""
    app = client.app_instance  # type: ignore[attr-defined]
    documented = list(app.openapi()["paths"])
    catalogue = [p for p in documented if "tracks" in p or "conditions" in p or "scenarios" in p]
    print(f"\ncatalogue routes: {catalogue}")

    assert len(catalogue) >= 5, f"the catalogue routes are not all registered: {catalogue}"
    assert all(p.startswith("/api/v1/") for p in catalogue), catalogue

    versioned = {p.rsplit("/", 1)[0] for p in documented if p.startswith("/api")}
    assert all(p.startswith("/api/v1") for p in versioned), (
        f"a second API version surface appeared: {sorted(versioned)}"
    )
