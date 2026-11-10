import json
from pathlib import Path
import pytest
from atlas_dev_engine import DevWorkspace, WorkspaceError


def make_project(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'app.py').write_text("print('original')\n", encoding='utf-8')
    (project / 'data.json').write_text('{"keep": true}', encoding='utf-8')
    (project / '.env').write_text('SECRET=do-not-copy', encoding='utf-8')
    (project / '.git').mkdir()
    (project / '.git' / 'HEAD').write_text('ref: refs/heads/main', encoding='utf-8')
    return project


def test_general_project_isolated_edit_and_diff(tmp_path):
    project = make_project(tmp_path)
    engine = DevWorkspace(project, tmp_path / 'engine')
    created = engine.create('website task')
    wid = created['workspace']
    engine.write_file(wid, 'app.py', "print('agent edit')\n")
    engine.write_file(wid, 'src/new.py', 'VALUE = 42\n')
    assert (project / 'app.py').read_text() == "print('original')\n"
    assert not (engine._workspace(wid) / 'data.json').exists()
    assert not (engine._workspace(wid) / '.env').exists()
    assert not (engine._workspace(wid) / '.git').exists()
    diff = engine.diff(wid)
    assert diff['modified'] == ['app.py']
    assert diff['added'] == ['src/new.py']
    assert diff['live_repository_changed'] is False


def test_delete_only_affects_workspace(tmp_path):
    project = make_project(tmp_path)
    engine = DevWorkspace(project, tmp_path / 'engine')
    wid = engine.create()['workspace']
    engine.delete_file(wid, 'app.py')
    assert (project / 'app.py').exists()
    assert engine.diff(wid)['deleted'] == ['app.py']


def test_path_traversal_and_absolute_path_rejected(tmp_path):
    project = make_project(tmp_path)
    engine = DevWorkspace(project, tmp_path / 'engine')
    wid = engine.create()['workspace']
    for path in ('../outside.txt', '/tmp/outside.txt', 'C:/outside.txt'):
        with pytest.raises(WorkspaceError):
            engine.write_file(wid, path, 'nope')


def test_unknown_check_rejected(tmp_path):
    project = make_project(tmp_path)
    engine = DevWorkspace(project, tmp_path / 'engine')
    wid = engine.create()['workspace']
    with pytest.raises(WorkspaceError):
        engine.run_check(wid, 'powershell -Command Remove-Item')


def test_export_contains_review_manifest_and_evidence_even_without_tests(tmp_path):
    project = make_project(tmp_path)
    engine = DevWorkspace(project, tmp_path / 'engine')
    wid = engine.create()['workspace']
    engine.write_file(wid, 'new.txt', 'hello')
    bundle = Path(engine.export_patch_bundle(wid))
    assert bundle.is_file()
    import zipfile
    with zipfile.ZipFile(bundle) as z:
        names = set(z.namelist())
    assert {'REVIEW-FIRST.json', 'WORKSPACE-BASELINE.json', 'TEST-EVIDENCE.json', 'HANDOFF-README.txt', 'files/new.txt'} <= names



def test_workspace_root_must_not_overlap_source_project(tmp_path):
    project = make_project(tmp_path)
    with pytest.raises(WorkspaceError):
        DevWorkspace(project, project / ".atlas-workspaces")
    with pytest.raises(WorkspaceError):
        DevWorkspace(project, tmp_path)


def test_symlink_paths_are_rejected(tmp_path):
    project = make_project(tmp_path)
    engine = DevWorkspace(project, tmp_path / "engine")
    wid = engine.create()["workspace"]
    workspace = engine._workspace(wid)
    outside = tmp_path / "outside.txt"
    outside.write_text("do not touch", encoding="utf-8")
    link = workspace / "escape.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this platform.")
    with pytest.raises(WorkspaceError):
        engine.read_file(wid, "escape.txt")
    with pytest.raises(WorkspaceError):
        engine.write_file(wid, "escape.txt", "overwrite")
    assert outside.read_text(encoding="utf-8") == "do not touch"



def test_workspace_integrity_metadata_is_read_only_and_tamper_evident(tmp_path):
    project = make_project(tmp_path)
    engine = DevWorkspace(project, tmp_path / "engine")
    wid = engine.create()["workspace"]
    workspace = engine._workspace(wid)
    with pytest.raises(WorkspaceError):
        engine.write_file(wid, ".atlas-workspace.json", "{}")
    with pytest.raises(WorkspaceError):
        engine.delete_file(wid, ".atlas-workspace.json")
    marker = workspace / ".atlas-workspace.json"
    marker.write_text('{"forged": true}', encoding="utf-8")
    with pytest.raises(WorkspaceError, match="integrity metadata"):
        engine.diff(wid)


def test_check_subdirectory_rejects_symlink_escape(tmp_path):
    project = make_project(tmp_path)
    engine = DevWorkspace(project, tmp_path / "engine")
    wid = engine.create()["workspace"]
    workspace = engine._workspace(wid)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = workspace / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this platform.")
    with pytest.raises(WorkspaceError, match="symbolic links or junctions"):
        engine.run_check(wid, "python_compile", "linked")


def test_workspace_root_symlink_is_rejected(tmp_path):
    project = make_project(tmp_path)
    engine = DevWorkspace(project, tmp_path / "engine")
    wid = engine.create()["workspace"]
    workspace = engine.root / wid
    moved = engine.root / (wid + "-real")
    workspace.rename(moved)
    try:
        workspace.symlink_to(moved, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this platform.")
    with pytest.raises(WorkspaceError, match="symbolic link or junction"):
        engine._workspace(wid)
