"""Compare known claimed generation without executing baseline source."""
import json
from pathlib import Path
import sys
from types import CodeType

def normalized(c):
    def const(v):
        if isinstance(v,CodeType):return normalized(v)
        if isinstance(v,tuple):return tuple(const(x)for x in v)
        if isinstance(v,frozenset):return frozenset(const(x)for x in v)
        return v
    return c.replace(co_filename='<generation>',co_firstlineno=1,co_linetable=b'',co_consts=tuple(const(x)for x in c.co_consts))

def verify_definitions(source, owner):
    def walk(code,obj):
        for c in code.co_consts:
            if not isinstance(c,CodeType) or c.co_name.startswith('<'):continue
            actual=obj[c.co_name] if isinstance(obj,dict) else getattr(obj,c.co_name)
            if isinstance(actual,type):walk(c,actual)
            else:
                actual=getattr(actual,'__func__',actual)
                if not hasattr(actual,'__code__') or normalized(actual.__code__)!=normalized(c):
                    raise RuntimeError('Loaded definition differs: '+c.co_qualname)
    walk(compile(source,'<known-generation>','exec',dont_inherit=True,optimize=0),owner)

def verify_generation(ns, root):
    version='.'.join(map(str,ns['bl_info']['version']))
    baselines=json.loads((Path(__file__).parent/'RELOAD-BASELINES.json').read_text())
    source=baselines[version]
    verify_definitions(source['__init__.py'],ns)
    mods={n:sys.modules[ns['__name__']+'.'+n]for n in ('core','adapter','workbench')}
    for n,m in mods.items():verify_definitions(source[n+'.py'],vars(m))
    if not (ns['Preview'] is mods['core'].Preview and type(ns['_preview'])is mods['core'].Preview
            and ns['Viewport'] is mods['adapter'].Viewport and mods['workbench'].Viewport is mods['adapter'].Viewport
            and ns['ComparisonViewport'] is mods['workbench'].ComparisonViewport
            and ns['PlaybackViewport'] is mods['workbench'].PlaybackViewport):
        raise RuntimeError('Root/dependency generation aliases differ')
    if version!='0.6.0' and ns['NamedCameraViewport'] is not mods['adapter'].NamedCameraViewport:
        raise RuntimeError('Named viewport alias differs')
    for n in ('require','validate_shots','shot_at'):
        if getattr(mods['workbench'],n)is not getattr(mods['core'],n):raise RuntimeError('Workbench core alias differs')

    for n in ('require','shading_capability','validate_shots'):
        if getattr(mods['adapter'],n)is not getattr(mods['core'],n):raise RuntimeError('Adapter core alias differs')
