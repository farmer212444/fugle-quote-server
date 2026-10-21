"""Fingerprint every source in the estimation runtime."""
import hashlib,pathlib
from importlib import metadata

def runtime_dependencies():
    try:reader=metadata.version('PyMuPDF')
    except metadata.PackageNotFoundError:reader=None
    return {'PyMuPDF':reader}
def code_fingerprint():
    root=pathlib.Path(__file__).resolve().parents[1];h=hashlib.sha256()
    paths=list((root/'tw_model_v880').glob('*.py'))+[root/'scripts/tw_v880_run.py']
    if (root/'requirements-model.txt').exists():paths.append(root/'requirements-model.txt')
    for p in sorted(paths):
        h.update(str(p.relative_to(root)).encode()+b'\0'+p.read_bytes()+b'\0')
    return h.hexdigest()
