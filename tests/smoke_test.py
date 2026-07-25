from __future__ import annotations
import shutil, tempfile
from pathlib import Path
from app import create_app

FIXTURE = Path(__file__).parent/'fixtures'/'sample_project'
with tempfile.TemporaryDirectory() as d:
    project=Path(d)/'sample_project'; shutil.copytree(FIXTURE, project)
    client=create_app(project).test_client()
    response=client.get('/api/catalog'); assert response.status_code==200
    cat=response.get_json()
    function_id=next(k for k,v in cat['nodes'].items() if v['node_type']=='function' and v['name']=='normalize_name')
    target_id=next(k for k,v in cat['nodes'].items() if v['node_type']=='module' and v['path']=='sample_pkg/normalization.py')
    preview=client.post('/api/refactor/move-function/preview',json={'function_id':function_id,'target_module_id':target_id})
    assert preview.status_code==200, preview.get_json()
    plan=preview.get_json(); assert len(plan['changes'])==2
    applied=client.post('/api/refactor/move-function/apply',json={'plan_id':plan['plan_id']})
    assert applied.status_code==200, applied.get_json()
    assert 'def normalize_name' not in (project/'sample_pkg'/'utils.py').read_text()
    assert 'def normalize_name' in (project/'sample_pkg'/'normalization.py').read_text()
    undone=client.post('/api/refactor/undo',json={})
    assert undone.status_code==200, undone.get_json()
    assert 'def normalize_name' in (project/'sample_pkg'/'utils.py').read_text()
print('Smoke test passed')
