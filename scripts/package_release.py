"""Allowlist-only deployment archive; never package runtime data or environment secrets."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parents[1]
TOP={'README.md','ACCEPTANCE.md','requirements.txt','package.json','Dockerfile','compose.yaml','Caddyfile','.env.example','.gitignore','.dockerignore'}
DIRS={'portal','static','skill','scripts','tests','docs'}


def main():
    destination=ROOT.parent/'digital-textbook-web-portal.zip'
    files=[]
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file():continue
        rel=path.relative_to(ROOT)
        if '__pycache__' in rel.parts or path.suffix=='.pyc':continue
        if (len(rel.parts)==1 and rel.name in TOP) or (len(rel.parts)>1 and rel.parts[0] in DIRS):
            if any(p in {'.env','node_modules','data','.git','.venv'} for p in rel.parts):
                raise RuntimeError('Unexpected private runtime file in release allowlist')
            files.append((rel.as_posix(),path.read_bytes()))
    repair=ROOT/'evidence/quality/repair-record.json'
    if repair.exists():files.append(('evidence/quality/repair-record.json',repair.read_bytes()))
    manifest={name:hashlib.sha256(data).hexdigest() for name,data in files}
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,data in files:archive.writestr('digital-textbook-web-portal/'+name,data)
        archive.writestr('digital-textbook-web-portal/RELEASE-MANIFEST.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:raise RuntimeError('Archive verification failed')
    receipt={'archive':destination.name,'files':len(files)+1,'bytes':destination.stat().st_size,
             'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
             'privateCourseMaterialsIncluded':False,'runtimeDataIncluded':False,'modelKeyIncluded':False,
             'liveModelTested':False,'publicDeploymentTested':False}
    (ROOT/'evidence/release.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
