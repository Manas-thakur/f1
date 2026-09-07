"""Read-only checks for the plan, local links, JSON fixtures and mockup inventory."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
import json
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
errors=[]
class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.ids=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        for key in ('href','src'):
            if key in a:self.links.append(a[key])
        if 'id' in a:self.ids.append(a['id'])

def check_link(path,target):
    target=target.strip('<>')
    u=urlsplit(target)
    if u.scheme or u.netloc or not u.path:return
    resolved=(path.parent/unquote(u.path)).resolve()
    try:resolved.relative_to(ROOT)
    except ValueError:
        errors.append(f'{path.relative_to(ROOT)}: link escapes package: {target}');return
    if not resolved.exists():errors.append(f'{path.relative_to(ROOT)}: missing {target}')

markdown=list(ROOT.rglob('*.md'));html=list(ROOT.rglob('*.html'));jsonfiles=list(ROOT.rglob('*.json'))
for p in markdown:
    text=p.read_text(encoding='utf-8')
    for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',text):check_link(p,target)
for p in html:
    parser=Links();parser.feed(p.read_text(encoding='utf-8'))
    for target in parser.links:check_link(p,target)
    if len(parser.ids)!=len(set(parser.ids)):errors.append(f'{p.name}: duplicate static IDs')
for p in jsonfiles:
    try:json.loads(p.read_text(encoding='utf-8'))
    except Exception as e:errors.append(f'{p.name}: invalid JSON: {e}')

schema=json.loads((ROOT/'01_contracts/schemas/telemetry-event.schema.json').read_text())
event=json.loads((ROOT/'01_contracts/schemas/telemetry-event.example.json').read_text())
if set(event)!=set(schema['required']):errors.append('Telemetry fixture fields mismatch')
if event['provenance']!='simulated':errors.append('Fixture provenance must be simulated')
scenario=json.loads((ROOT/'03_simulation/scenario.example.json').read_text())
if scenario['observation']['expose_rival_energy']:errors.append('Fixture leaks rival energy')
if not scenario['synthetic']:errors.append('Scenario is not marked synthetic')
for folder in sorted(ROOT.glob('[0-9][0-9]_*')):
    if folder.name not in ('00_program','16_sources') and not (folder/'AGENT_BRIEF.md').exists():errors.append(f'{folder.name}: no agent brief')
for name in ['index.html','app.html','driver.html','concepts.html','landing.html','simulation.html']:
    if not (ROOT/'12_design/mockups'/name).exists():errors.append(f'missing mockup {name}')

words=sum(len(re.findall(r'\b\w+\b',p.read_text(encoding='utf-8'))) for p in markdown)
print(f'{len(markdown)} Markdown files; {len(html)} HTML entrypoints; {len(jsonfiles)} JSON files; approximately {words:,} documentation words.')
print('Checks: local links, static HTML IDs, JSON parsing, fixture provenance, hidden-state flag, agent briefs and mockup inventory.')
if errors:
    print('\n'.join(errors));sys.exit(1)
print('PASS — package structure and local references. Browser behaviour and model correctness are separate checks.')
