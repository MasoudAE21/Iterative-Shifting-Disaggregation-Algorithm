"""Plot full intervals of every bill intersecting the confirmed validation dates."""
from pathlib import Path
from datetime import date, timedelta
import csv, json
from collections import Counter
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/town_analysis'; OUT.mkdir(parents=True,exist_ok=True)
START=date(2025,1,2); END=date(2025,2,28)
selected=[]
with (ROOT/'data/prepared/bill_Customers_Town_Q.csv').open(encoding='utf-8-sig',newline='') as stream:
    for row in csv.DictReader(stream):
        a=date.fromisoformat(row['FromDate']); b=date.fromisoformat(row['ToDate'])
        if a<=END and b>=START: selected.append((a,b,row['SubscriptionNumber']))
assert selected
lo=min(a for a,b,i in selected); hi=max(b for a,b,i in selected)
changes=Counter()
for a,b,i in selected: changes[a]+=1; changes[b+timedelta(days=1)]-=1
series=[]; active=0; day=lo
while day<=hi:
    active+=changes[day]
    series.append((day,active,'before target' if day<START else 'after target' if day>END else 'target'))
    day+=timedelta(days=1)
assert sum(n for d,n,k in series)==sum((b-a).days+1 for a,b,i in selected)
for day in [lo,START,END,hi]:
    assert dict((d,n) for d,n,k in series)[day]==sum(a<=day<=b for a,b,i in selected)
with (OUT/'selected_bill_daily_counts.csv').open('w',newline='',encoding='utf-8') as stream:
    writer=csv.writer(stream); writer.writerow(['date','active_selected_bills','position']); writer.writerows(series)
summary={'target_start':str(START),'target_end_inclusive':str(END),'target_days':(END-START).days+1,
 'selected_bills':len(selected),'selected_customers':len({i for a,b,i in selected}),
 'earliest_bill_start':str(lo),'latest_bill_end':str(hi),
 'bills_extending_before':sum(a<START for a,b,i in selected),
 'bills_extending_after':sum(b>END for a,b,i in selected),
 'bills_extending_both':sum(a<START and b>END for a,b,i in selected),
 'bills_wholly_inside':sum(a>=START and b<=END for a,b,i in selected),
 'bill_days_before':sum(n for d,n,k in series if d<START),
 'bill_days_inside':sum(n for d,n,k in series if START<=d<=END),
 'bill_days_after':sum(n for d,n,k in series if d>END),
 'minimum_target_daily_bills':min(n for d,n,k in series if START<=d<=END),
 'maximum_target_daily_bills':max(n for d,n,k in series if START<=d<=END)}
(OUT/'selected_bill_coverage_summary.json').write_text(json.dumps(summary,indent=2))

# Two views keep the exceptional multi-year tails visible without hiding the main boundary pattern.
W,H=1800,1320
im=Image.new('RGB',(W,H),'#f7f9fc'); draw=ImageDraw.Draw(im)
fontdir=Path('C:/Windows/Fonts')
def font(size,bold=False): return ImageFont.truetype(str(fontdir/('arialbd.ttf' if bold else 'arial.ttf')),size)
ink='#142b43'; muted='#536579'; teal='#087f8c'; orange='#d97932'
draw.text((90,42),'Bills overlapping the validation period',font=font(44,True),fill=ink)
draw.text((90,104),'January 2–February 28, 2025  |  Inclusive bill dates  |  Counts, not consumption',font=font(25),fill=muted)
draw.text((90,157),f"{len(selected):,} selected bills   ·   {summary['selected_customers']:,} customers   ·   {summary['target_days']} target days",font=font(28,True),fill=ink)

def panel(top,bottom,leftdate,rightdate,title,stepmonths):
    x0,x1=130,1690; y0,y1=top+60,bottom-65
    draw.text((90,top),title,font=font(28,True),fill=ink)
    ymax=10000
    def x(d):return x0+(d-leftdate).days/(rightdate-leftdate).days*(x1-x0)
    def y(n):return y1-n/ymax*(y1-y0)
    draw.rectangle((x0,y0,x1,y1),fill='white')
    draw.rectangle((x(START),y0,x(END+timedelta(days=1)),y1),fill='#d9f0ed')
    for n in range(0,10001,2000):
        yy=y(n); draw.line((x0,yy,x1,yy),fill='#dbe2e9',width=1)
        draw.text((x0-84,yy-13),f'{n:,}',font=font(21),fill=muted)
    points=[(x(d),y(n)) for d,n,k in series if leftdate<=d<=rightdate]
    if points:draw.line(points,fill=orange,width=4)
    target=[(x(d),y(n)) for d,n,k in series if START<=d<=END]
    draw.line(target,fill=teal,width=5)
    for boundary in [START,END+timedelta(days=1)]:
        xx=x(boundary)
        for yy in range(int(y0),int(y1),14):draw.line((xx,yy,xx,yy+6),fill=teal,width=2)
    month=date(leftdate.year,leftdate.month,1)
    while month<=rightdate:
        if month>=leftdate:
            label=month.strftime('%b %Y'); xx=x(month)
            draw.line((xx,y1,xx,y1+6),fill=muted,width=1)
            draw.text((xx-45,y1+16),label,font=font(20),fill=muted)
        total=month.year*12+month.month-1+stepmonths; month=date(total//12,total%12+1,1)

panel(225,740,date(2024,10,1),date(2025,7,1),'A. Boundary detail — October 2024 to June 2025',1)
panel(780,1190,lo,hi,'B. Full extent — all selected bill intervals, including long tails',6)
draw.text((130,1210),'Orange: outside target     Teal line / shaded band: validation period',font=font(24),fill=ink)
draw.text((130,1255),'Each bill contributes 1 on every date from FromDate through ToDate. No bills are prorated or excluded.',font=font(22),fill=muted)
im.save(OUT/'selected_bill_daily_coverage.png')
print(json.dumps(summary,indent=2))
