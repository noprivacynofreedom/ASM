import pytest
from atlas_dev_engine import DevWorkspace
from atlas_manager import AtlasManager, ManagerError


def test_manager_validates_cycles_and_roles(tmp_path):
    project = tmp_path / 'project'; project.mkdir(); (project / 'a.txt').write_text('a')
    manager = AtlasManager(DevWorkspace(project, tmp_path / 'engine'))
    with pytest.raises(ManagerError):
        manager.create_run('goal', tasks=[
            {'id':'a','title':'A','depends_on':['b']},
            {'id':'b','title':'B','depends_on':['a']},
        ])
    with pytest.raises(ManagerError):
        manager.create_run('goal', tasks=[{'id':'a','title':'A','role':'root'}])


def test_manager_creates_separate_workspaces_and_handoff(tmp_path):
    project = tmp_path / 'project'; project.mkdir(); (project / 'a.txt').write_text('original')
    engine = DevWorkspace(project, tmp_path / 'engine')
    manager = AtlasManager(engine)
    run = manager.create_run('Build a thing', tasks=[
        {'id':'one','title':'first','role':'coder'},
        {'id':'two','title':'second','role':'tester','depends_on':['one']},
    ])
    def worker(task, wid, dev):
        dev.write_file(wid, f"{task['id']}.txt", task['title'])
        return {'status':'completed','summary':'implemented in isolated workspace'}
    result = manager.run_ready_tasks(run['id'], worker, max_tasks=2)
    assert result['status'] == 'completed'
    assert result['counts']['completed'] == 2
    assert result['tasks'][0]['workspace'] != result['tasks'][1]['workspace']
    bundles = manager.handoff(run['id'])
    assert len(bundles) == 2
    assert (project / 'a.txt').read_text() == 'original'


def test_manager_never_claims_execution_without_worker(tmp_path):
    project = tmp_path / 'project'; project.mkdir()
    manager = AtlasManager(DevWorkspace(project, tmp_path / 'engine'))
    run = manager.create_run('goal', tasks=[{'id':'one','title':'task'}])
    with pytest.raises(ManagerError):
        manager.run_ready_tasks(run['id'], None)



def test_manager_rejects_malformed_dependency_values(tmp_path):
    project = tmp_path / "project"; project.mkdir()
    manager = AtlasManager(DevWorkspace(project, tmp_path / "engine"))
    with pytest.raises(ManagerError):
        manager.create_run("goal", tasks=[{"id": "a", "title": "A", "depends_on": "bc"}])
    with pytest.raises(ManagerError):
        manager.create_run("goal", tasks=[{"id": "a", "title": "A", "depends_on": ["b", "b"]}])


def test_manager_persists_running_state_before_worker_returns(tmp_path):
    project = tmp_path / "project"; project.mkdir()
    manager = AtlasManager(DevWorkspace(project, tmp_path / "engine"))
    run = manager.create_run("goal", tasks=[{"id": "one", "title": "task"}])
    observed = {}
    def worker(task, wid, dev):
        saved = manager._load(run["id"])
        observed["status"] = saved["tasks"][0]["status"]
        observed["workspace"] = saved["tasks"][0]["workspace"]
        return {"status": "completed"}
    manager.run_ready_tasks(run["id"], worker)
    assert observed["status"] == "running"
    assert observed["workspace"]
