"""Project-scoped record semantics for Python 3.5; no external dataclasses dependency.

Supports the exact Config/PalmGeometry/FingerFeatures contract used here:
ordered fields, required/default arguments, positional/keyword validation,
repr/equality, replace, and recursively deep-copied asdict. No frozen, InitVar,
inheritance, default_factory, slots, or ordering is claimed.
"""
import copy

class _Missing(object):
    pass
MISSING = _Missing()

class Field(object):
    def __init__(self, name, default=MISSING):
        self.name, self.default = name, default

def fields(value):
    cls = value if isinstance(value, type) else type(value)
    if not hasattr(cls, '_record_fields'):
        raise TypeError('fields() requires a project record')
    return cls._record_fields

def dataclass(cls):
    specs = tuple(Field(name, default) for name, default in cls._field_specs)
    names = tuple(item.name for item in specs)
    optional = False
    for item in specs:
        if item.default is not MISSING:
            optional = True
            setattr(cls, item.name, item.default)
        elif optional:
            raise TypeError('non-default argument follows default argument')
    cls._record_fields = specs
    def init(self, *args, **kwargs):
        if len(args) > len(specs):
            raise TypeError('Too many positional arguments')
        unknown = set(kwargs) - set(names)
        if unknown:
            raise TypeError('Unexpected fields: ' + ','.join(sorted(unknown)))
        for i, field in enumerate(specs):
            if i < len(args):
                if field.name in kwargs:
                    raise TypeError('Multiple values for ' + field.name)
                value = args[i]
            elif field.name in kwargs:
                value = kwargs[field.name]
            elif field.default is not MISSING:
                value = field.default
            else:
                raise TypeError('Missing required field: ' + field.name)
            setattr(self, field.name, value)
    def representation(self):
        return cls.__name__ + '(' + ', '.join(f.name+'='+repr(getattr(self,f.name)) for f in specs) + ')'
    def equal(self, other):
        if type(other) is not cls:
            return NotImplemented
        return tuple(getattr(self,f.name) for f in specs) == tuple(getattr(other,f.name) for f in specs)
    cls.__init__, cls.__repr__, cls.__eq__ = init, representation, equal
    cls.__hash__ = None
    return cls

def asdict(value):
    fields(value)
    def recurse(obj):
        if hasattr(type(obj), '_record_fields'):
            return {f.name: recurse(getattr(obj,f.name)) for f in fields(obj)}
        if isinstance(obj, tuple) and hasattr(obj, '_fields'):
            return type(obj)(*(recurse(x) for x in obj))
        if isinstance(obj, (list,tuple)):
            return type(obj)(recurse(x) for x in obj)
        if isinstance(obj, dict):
            return type(obj)((recurse(k),recurse(v)) for k,v in obj.items())
        return copy.deepcopy(obj)
    return recurse(value)

def replace(value, **changes):
    fs=fields(value)
    known={f.name for f in fs}
    if set(changes)-known:
        raise TypeError('Unexpected replacement fields')
    return type(value)(**{f.name: changes.get(f.name,getattr(value,f.name)) for f in fs})
