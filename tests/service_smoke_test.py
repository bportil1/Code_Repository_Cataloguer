from __future__ import annotations
import shutil, tempfile
from pathlib import Path
from catalog.catalog_builder import build_catalog
from catalog.refactor.function_mover import FunctionMoveService

FIXTURE = Path(__file__).parent/'fixtures'/'sample_project'
with tempfile.TemporaryDirectory() as d:
    project=Path(d)/'sample_project'; shutil.copytree(FIXTURE, project)
    service=FunctionMoveService(project, lambda: build_catalog(project))
    cat=service.catalog()
    function_id=next(k for k,v in cat.nodes.items() if v.node_type=='function' and v.name=='normalize_name')
    target_id=next(k for k,v in cat.nodes.items() if v.node_type=='module' and v.path=='sample_pkg/normalization.py')
    plan=service.preview(function_id,target_id)
    assert len(plan.changes)==2
    result=service.apply(plan.id); assert result['success']
    assert 'def normalize_name' not in (project/'sample_pkg'/'utils.py').read_text()
    assert 'def normalize_name' in (project/'sample_pkg'/'normalization.py').read_text()
    undone=service.undo_last(); assert undone['success']
    assert 'def normalize_name' in (project/'sample_pkg'/'utils.py').read_text()
print('Service smoke test passed')
