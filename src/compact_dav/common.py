import functools
import logging
import re
import sys
import urllib

from .config import Config

_logger = logging.getLogger("compact_dav")
_logger.propagate = False  # don't leak to any root-logger handlers

_out_handler: logging.StreamHandler


class _Formatter(logging.Formatter):
    _COLORS = {
        logging.DEBUG:   '\x1b[32m',
        logging.INFO:    '\x1b[33m',
        logging.WARNING: '\x1b[96m',
        logging.ERROR:   '\x1b[31m',
    }
    _LABELS = {
        logging.DEBUG:   lambda r: f"% {r.funcName}()",
        logging.INFO:    lambda r: f"% {r.funcName}()",
        logging.WARNING: lambda _: "warning",
        logging.ERROR:   lambda _: "error",
    }

    def format(self, record):
        color = self._COLORS.get(record.levelno, '\x1b[0m')
        label = self._LABELS.get(
            record.levelno,
            lambda r: getattr(r, 'label', 'note'),
        )(record)
        msg = record.getMessage()
        if Config.get('no-colors', False):
            return f"{label}: {msg}"
        return f"{color}{label}:\x1b[0m {msg}"


def _init_logging():
    global _out_handler
    fmt = _Formatter()

    _out_handler = logging.StreamHandler(sys.stdout)
    _out_handler.addFilter(lambda r: r.levelno < logging.ERROR)
    _out_handler.setLevel(logging.INFO)
    _out_handler.setFormatter(fmt)

    err = logging.StreamHandler(sys.stderr)
    err.setLevel(logging.ERROR)
    err.setFormatter(fmt)

    _logger.addHandler(_out_handler)
    _logger.addHandler(err)
    _logger.setLevel(logging.DEBUG)


_init_logging()


def configure_logging():
    """Set the effective verbosity level from active Config flags."""
    if Config.get('debug', False):
        level = logging.DEBUG
    elif Config.get('quiet', False):
        level = logging.ERROR
    else:
        level = logging.INFO
    _out_handler.setLevel(level)


# ── utility functions ─────────────────────────────────────────────────────────

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


# ── log wrappers ──────────────────────────────────────────────────────────────

def error(msg, code=None, ret=False):
    _logger.error(msg, stacklevel=2)
    if code is not None:
        sys.exit(code)
    return ret


def warning(msg, ret=False):
    _logger.warning(msg, stacklevel=2)
    return ret


def verbose(msg, ret=True):
    if Config.get('verbose', False):
        _logger.info(msg, stacklevel=2, extra={'label': 'verbose'})
    return ret


def debug(msg, force=False, ret=True):
    _logger.log(logging.INFO if force else logging.DEBUG, msg, stacklevel=2)
    return ret
