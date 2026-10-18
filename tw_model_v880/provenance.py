"""Fingerprint every source in the estimation runtime."""
import hashlib,pathlib
def code_fingerprint():
    root=pathlib.Path(__file__).resolve().parents[1];h=hashlib.sha256()
    for p in sorted(list((root/'tw_model_v880').glob('*.py'))+[root/'scripts/tw_v880_run.py']):
        h.update(str(p.relative_to(root)).encode()+b'\0'+p.read_bytes()+b'\0')
    return h.hexdigest()
