"""Allowlisted, size-limited review packaging; no raw/bulk tables or environments."""
import csv,hashlib,json,re,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def package():
    allowed=[]
    for name in ['run_pipeline.py','requirements.txt','README.md','.gitignore','scripts/audit_data.py','scripts/execute_review.py','scripts/package_review.py']:
        allowed.append(ROOT/name)
    for folder,pattern in [('isd','*.py'),('tests','*.py'),('configs','*.json'),('tests/fixtures','*')]:
        allowed.extend(p for p in (ROOT/folder).glob(pattern) if p.is_file())
    for p in (ROOT/'handoff'/'implementation').rglob('*'):
        if p.is_file() and p.name!='bundle_inventory.json' and p.suffix in ('.md','.json','.csv','.txt','.xml'): allowed.append(p)
    for name in ['data_audit.md','data_schema.json','sample_notes.json','questions.md']: allowed.append(ROOT/'handoff'/name)
    allowed=sorted(set(p for p in allowed if p.exists()))
    for p in allowed:
        if p.stat().st_size>2*1024*1024: raise ValueError('Unexpectedly large review member '+str(p))
        parts=p.relative_to(ROOT).parts
        if any(x in parts for x in ['data','outputs','.venv','__pycache__','.git','.pytest_cache']): raise ValueError('Forbidden path')
    # IDs are not reversibly mapped outside the machine; check source IDs against text members.
    with (ROOT/'data'/'bill_1403.csv').open(encoding='utf-8-sig',newline='') as f: ids={r['SubscriptionNumber'] for r in csv.DictReader(f)}
    for p in allowed:
        text=p.read_text(encoding='utf-8-sig')
        if set(re.findall(r'(?<![A-Za-z0-9])\d{11}(?![A-Za-z0-9])',text)) & ids: raise ValueError('Raw customer ID in review member '+str(p))
    index={'members':[{'path':str(p.relative_to(ROOT)).replace(chr(92),'/'),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in allowed],'policy':'Allowlisted text/source/aggregate summaries and small fixtures only; all source customer identifiers screened; no reversible map; no bulk Parquet or checkpoints','full_production_run':False}
    (ROOT/'handoff'/'implementation'/'bundle_inventory.json').write_text(json.dumps(index,indent=2),encoding='utf-8');allowed.append(ROOT/'handoff'/'implementation'/'bundle_inventory.json')
    target=ROOT/'handoff'/'implementation_review_bundle.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for p in allowed: z.write(p,str(p.relative_to(ROOT)).replace(chr(92),'/'))
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        assert len(z.namelist())==len(set(z.namelist()))
        assert all(not n.endswith(('.parquet','.npz','.npy','.zip')) for n in z.namelist())
    print('Validated review ZIP:',target,'bytes',target.stat().st_size,'members',len(allowed))

if __name__=='__main__': package()
