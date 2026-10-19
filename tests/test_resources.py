import pytest

from oegem import OEError
from oegem.resources import (GEM_ROOT, RELEASE_COLUMNS, WALK_COLUMNS, archive, delete, ensure_folder_tree,
                             exists, list_children, list_forecasts, list_releases, make_folder, move,
                             release_sort_key, resolve_release, walk)

SHARED = "demo-shared/team-scenarios"


def test_list_children_and_walk(client):
    assert [c["Name"] for c in list_children(client, GEM_ROOT)] == ["Extension"]
    tree = walk(client, GEM_ROOT, max_depth=4)
    assert list(tree.columns) == WALK_COLUMNS
    assert {"Demo26_1 5yr", "Demo26_2 5yr", "Demo26_2 25yr", "Demo26_0 5yr"} <= set(tree["name"])
    assert tree.loc[tree["name"] == "Demo26_0 5yr", "depth"].item() == 4
    assert list(walk(client, GEM_ROOT, max_depth=1)["name"]) == ["Extension"]


def test_release_sort_key():
    assert release_sort_key("Sep26_2 5yr") == (2026, 9, 2)
    assert release_sort_key("Jun26_1 25yr") == (2026, 6, 1)
    assert release_sort_key("Dec25 5yr") == (2025, 12, 0)
    assert release_sort_key("Demo26_2 5yr") == (2026, 0, 2)
    assert release_sort_key("Model documentation") is None
    assert release_sort_key("2026-01_1") is None


def test_list_releases(client):
    rel = list_releases(client)
    assert list(rel.columns) == RELEASE_COLUMNS
    assert list(rel["name"]) == ["Demo26_2 5yr", "Demo26_2 25yr", "Demo26_1 5yr", "Demo26_0 5yr"]
    assert list(rel["is_previous"]) == [False, False, False, True]
    assert list(rel["horizon"]) == ["5yr", "25yr", "5yr", "5yr"]
    assert rel["vintage"].iloc[0] == "2026-x-2"                     # "Demo" is not a month name
    from oegem.resources import _vintage
    assert _vintage((2026, 9, 2)) == "2026-09-2" and _vintage(None) is None
    assert rel["id"].notna().all()


@pytest.mark.parametrize("spec, name", [
    ("latest", "Demo26_2 5yr"), ("latest:5yr", "Demo26_2 5yr"), ("latest:25yr", "Demo26_2 25yr"),
    ("Demo26_1 5yr", "Demo26_1 5yr"), ("demo26_1  5YR", "Demo26_1 5yr"), ("Demo26_0 5yr", "Demo26_0 5yr"),
    ("Extension/Demo26_1 5yr", "Demo26_1 5yr"), (GEM_ROOT + "/Extension/Demo26_2 25yr", "Demo26_2 25yr"),
    ("/" + GEM_ROOT + "/Extension/Demo26_1 5yr", "Demo26_1 5yr"), ("/me/examples/demo-copy", "demo-copy"),
])
def test_resolve_release_forms(client, spec, name):
    res = resolve_release(client, spec)
    assert res["Name"] == name and res["Id"]


def test_resolve_release_by_id_and_errors(client):
    rid = list_releases(client)["id"].iloc[2]
    res = resolve_release(client, rid)
    assert res["Id"] == rid and res["Name"] == "Demo26_1 5yr"
    unknown = "00000000-0000-4000-8000-000000000000"
    assert resolve_release(client, unknown)["Id"] == unknown
    with pytest.raises(ValueError, match="Did you mean"):
        resolve_release(client, "Demo26_3 5yr")
    with pytest.raises(ValueError, match="Horizons found: 25yr, 5yr"):
        resolve_release(client, "latest:10yr")
    with pytest.raises(ValueError):
        resolve_release(client, "  ")


def test_folders_create_and_reuse(client):
    ensure_folder_tree(client, "/me/oegem-runs/test/sub")
    for path in ("/me/oegem-runs", "/me/oegem-runs/test", "me/oegem-runs/test/sub"):
        assert exists(client, path)
    first = make_folder(client, "/me/oegem-runs/test")
    assert make_folder(client, "/me/oegem-runs/test")["Id"] == first["Id"]
    with pytest.raises(ValueError, match="exist_ok"):
        make_folder(client, "/me/oegem-runs/test", exist_ok=False)
    made = make_folder(client, "/me/oegem-runs/new")
    assert made["Path"] == "/me/oegem-runs/new"
    with pytest.raises(OEError) as err:
        make_folder(client, "/me/missing-parent/x")
    assert err.value.status == 404
    assert not exists(client, "/me/nothing-here")


def test_move_and_delete_in_user_area(client):
    make_folder(client, "/me/a")
    make_folder(client, "/me/b")
    moved = move(client, "/me/a", "/me/b")
    assert moved["Path"] == "/me/b/a"
    assert exists(client, "/me/b/a") and not exists(client, "/me/a")
    with pytest.raises(ValueError, match="confirm=True"):
        delete(client, "/me/b")
    delete(client, "/me/b", confirm=True)
    assert not exists(client, "/me/b") and not exists(client, "/me/b/a")
    with pytest.raises(ValueError, match="workspace root"):
        delete(client, "/me", confirm=True)


def test_shared_delete_refused_then_archive(client):
    item = SHARED + "/old-scenario"
    with pytest.raises(OEError) as err:
        delete(client, item, confirm=True)
    assert err.value.status == 403 and "archive" in str(err.value).lower()
    assert exists(client, item)
    archived = archive(client, item, SHARED + "/$Archive")
    assert archived["Path"].endswith("$Archive/old-scenario")
    delete(client, SHARED + "/$Archive/old-scenario", confirm=True)
    assert not exists(client, SHARED + "/$Archive/old-scenario")
    with pytest.raises(ValueError, match="Archive folder"):
        archive(client, "/me/examples/demo-copy", SHARED + "/$Nowhere")


def test_release_tree_is_read_only(client):
    with pytest.raises(OEError) as err:
        make_folder(client, GEM_ROOT + "/Extension/mine")
    assert err.value.status == 403


def test_list_forecasts(client):
    found = list_forecasts(client)
    assert list(found.columns) == WALK_COLUMNS
    assert list(found["name"]) == ["demo-copy"]
    ensure_folder_tree(client, "/me/runs/r1")
    client.session.add_forecast("me/runs/r1/scenario-a", parent=found["id"].iloc[0])
    assert list(list_forecasts(client)["name"]) == ["demo-copy", "scenario-a"]
