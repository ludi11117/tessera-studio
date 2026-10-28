"""Offline font partitioner. Retains the original Unicode repertoire without UI-only cropping."""
import hashlib
import json
import re
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path('D:/CodexWork/cache/intent-workbench-assets/SourceHanSansSC.otf')
ASSETS = ROOT/'static/assets'


def rename_font(font):
    names={1:'Intent Sans SC',2:'Regular',3:'IntentSansSC-Regular-subset-v1',4:'Intent Sans SC Regular',6:'IntentSansSC-Regular',16:'Intent Sans SC',17:'Regular',18:'Intent Sans SC Regular',21:'Intent Sans SC',22:'Regular'}
    for record in font['name'].names:
        if record.nameID in names:record.string=names[record.nameID].encode(record.getEncoding(),errors='replace')
    cff=font['CFF '].cff
    cff.fontNames=['IntentSansSC-Regular']
    for top in cff.topDictIndex:
        top.FamilyName='Intent Sans SC';top.FullName='Intent Sans SC Regular'
        if hasattr(top,'FDArray'):
            for fd in top.FDArray:
                if hasattr(fd,'FontName'):fd.FontName=fd.FontName.replace('SourceHanSansSC','IntentSansSC')


def refresh_names():
    manifest=json.loads((ASSETS/'font-partitions.json').read_text('utf-8'))
    repertoire=set(TTFont(SOURCE).getBestCmap());seen=set()
    for part in manifest['partitions']:
        file=ASSETS/part['file'];font=TTFont(file,recalcTimestamp=False);rename_font(font);font.save(file)
        points=set(font.getBestCmap());assert not points&seen;seen|=points
        part.update(bytes=file.stat().st_size,sha256=hashlib.sha256(file.read_bytes()).hexdigest(),sample_unicode=min(points))
        print(part['file'],part['bytes'],flush=True)
    assert seen==repertoire
    (ASSETS/'font-partitions.json').write_text(json.dumps(manifest,indent=2),'utf-8')


def ranges(points):
    runs = []
    for cp in sorted(points):
        if runs and cp == runs[-1][1]+1: runs[-1][1] = cp
        else: runs.append([cp,cp])
    return ','.join('U+%X'%a if a == b else 'U+%X-%X'%(a,b) for a,b in runs)


def main():
    original = TTFont(SOURCE, recalcTimestamp=False)
    repertoire = set(original.getBestCmap())
    common = set(range(0x400)) | set(range(0x2000,0x3040)) | set(range(0xFF00,0xFFF0))
    for lead in range(0xB0,0xD8):
        for trail in range(0xA1,0xFF):
            try: common.add(ord(bytes([lead,trail]).decode('gb2312')))
            except UnicodeDecodeError: pass
    for file in (ROOT/'static').glob('*'):
        if file.suffix in ('.html','.js','.css'):
            common.update(ord(c) for c in re.findall(r'[\u3400-\u9fff]',file.read_text('utf-8')))
    common &= repertoire
    groups = [('common',common)]
    remaining = repertoire-common
    for base in sorted({cp//4096*4096 for cp in remaining}):
        groups.append(('%x'%base,{cp for cp in remaining if base<=cp<base+4096}))
    manifest = {'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(), 'original_unicode_count':len(repertoire), 'partitions':[]}
    faces = []
    union = set()
    for name, points in groups:
        assert points and not union&points
        union |= points
        font = TTFont(SOURCE, recalcTimestamp=False)
        options = subset.Options(); options.layout_features = ['*']
        sub = subset.Subsetter(options=options); sub.populate(unicodes=points); sub.subset(font)
        # The source font reserves "Source"; derived subsets get a new family name.
        rename_font(font)
        font.flavor='woff2'
        filename='IntentSans-'+name+'.woff2'; file=ASSETS/filename; font.save(file)
        assert set(TTFont(file).getBestCmap()) == points
        manifest['partitions'].append({'file':filename,'unicode_count':len(points),'sample_unicode':min(points),'bytes':file.stat().st_size,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
        faces.append('@font-face{font-family:"Intent Sans SC";font-weight:400;font-style:normal;font-display:swap;src:url("/assets/'+filename+'") format("woff2");unicode-range:'+ranges(points)+'}')
        print(filename,len(points),file.stat().st_size,flush=True)
    assert union == repertoire
    (ASSETS/'fonts.css').write_text('\n'.join(faces)+'\n','utf-8')
    manifest['partitioned_unicode_count']=len(union)
    (ASSETS/'font-partitions.json').write_text(json.dumps(manifest,indent=2),'utf-8')
    print('PASS: complete Unicode coverage, disjoint partitions',flush=True)


if __name__ == '__main__': refresh_names() if '--refresh-names' in sys.argv else main()
