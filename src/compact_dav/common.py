import functools
import re
import sys
import urllib

from .logger import warning
from .config import Config


def getFromDict(dataDict, mapList, valueOnError=None):
    try:
        return functools.reduce(lambda d, k: d[k], mapList, dataDict)
    except Exception:
        return valueOnError


def makeHuman(value, addBytes=False, base=1000, decimals=1):
    if not Config['human']:
        return f"{value}{' bytes' if addBytes else ''}"

    units = {
        1000: ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"),
        1024: ("B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"),
    }

    base = base if base in units else 1000
    i = 1
    while i < len(units[base]) and value > (base ** i):
        i += 1

    display = ((value * (10 ** decimals)) / (base ** (i - 1))) / (10 ** decimals) if i > 1 else value
    return f"{display!s:.3} {units[base][i - 1]}"


def relativePath(r, var, root, endpoint):
    val = r[var].replace(endpoint, "")
    val = val.replace(root, "", 1)
    val = urllib.parse.unquote(val)

    sp = val.split('/')
    if 'type' in r and r['type'] == 'd' and len(sp) > 1:
        val = f"/{sp[-2]}"
    elif len(sp) > 1:
        val = "/".join(sp[1:])

    return val


def listToDict(*args):
    return dict(zip(map(str, range(len(*args))), *args))


def getValueByTagReference(v, *args):
    for m in re.findall(r'@([0-9]+)|@{([\w\.\-]+)}', v):
        rv = m[1] if m[1] > '' else m[0]
        rs = f"@{{{m[1]}}}" if m[1] > '' else f"@{m[0]}"
        ov = None
        for d in args:
            ov = getFromDict(d, rv.split('.'))
            if ov:
                break
        if ov is None:
            warning(f"value reference: tag {rs} does not exist in provided data")
        v = v.replace(rs, str(ov)) if ov else v
    return v.replace('@@', '@')
