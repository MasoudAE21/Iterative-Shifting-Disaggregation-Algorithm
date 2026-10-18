"""Package a small allowlisted handoff; never include raw input or bulk output."""
from pathlib import Path
import csv,hashlib,json,zipfile
ROOT=Path(__file__).resolve().parents[1]

def main():
    handoff=ROOT/'handoff';out=ROOT/'outputs'
    sample=[];seen=set()
    with (out/'customer_peak_consumption.csv').open(newline='',encoding='utf-8') as f:
        for row in csv.DictReader(f):
            value=row['peakCosumptionValue'];kind='missing' if value=='' else 'zero' if float(value)==0 else 'positive'
            if len(sample)<10 or kind not in seen:
                sample.append({'SubscriptionNumber':f'CUSTOMER_{len(sample)+1:03d}','peakCosumptionValue':value});seen.add(kind)
            if len(sample)>=10 and len(seen)==3: break
    sample_path=handoff/'peak_output_sample_pseudonymized.csv'
    with sample_path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=['SubscriptionNumber','peakCosumptionValue']);writer.writeheader();writer.writerows(sample)
    files=[ROOT/'run_pipeline.py',ROOT/'requirements.txt',ROOT/'README.md']
    for folder,pattern in [('isd','*.py'),('tests','*.py'),('configs','*.json'),('scripts','*.py')]: files+=sorted((ROOT/folder).glob(pattern))
    files+=sorted((ROOT/'tests/fixtures').glob('*.csv'))+[ROOT/'tests/fixtures/README.md']
    files += [handoff/name for name in ['peak_review_resolutions.md','peak_tests.xml','peak_tests.txt','peak_export_equivalence.json','peak_memory_benchmarks.json','peak_final_verification.json','peak_output_sample_pseudonymized.csv']]
    files += [out/name for name in ['peak_summary.md','peak_daily_totals.csv','run_manifest.json','run_summary.csv','aggregate_daily_summary.csv','iteration_summary.csv']]
    files += [handoff/'implementation'/name for name in ['algorithm_specification.md','supplied_specification.md','recorded_decisions.md']]
    inventory={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    bundle=handoff/'peak_review_bundle.zip'
    with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files:z.write(p,str(p.relative_to(ROOT)).replace('\\','/'))
        z.writestr('bundle_inventory.json',json.dumps(inventory,indent=2))
    with zipfile.ZipFile(bundle) as z:
        assert z.testzip() is None
        for name,digest in inventory.items(): assert hashlib.sha256(z.read(name)).hexdigest()==digest
    print(f'{bundle}: {bundle.stat().st_size} bytes, {len(files)+1} members; all hashes verified')
if __name__=='__main__': main()
