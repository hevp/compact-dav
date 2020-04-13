import sys, inspect, re, urllib, functools

# current options global
options = {}

def getFromDict(dataDict, mapList, valueOnError=None):
    try:
        return functools.reduce(lambda d, k: d[k], mapList, dataDict)
    except Exception:
        return valueOnError

def makeHuman(value, addBytes=False, base=1000, decimals=1):
    if not options['human']:
        return "%d%s" % (value, " bytes" if addBytes else "")

    units = {
        1000: ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"),
        1024: ("B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB")
    }

    base = base if base in units.keys() else 1000
    i = 1
    while i < len(units[base]) and value > (base ** i):
        i += 1

    return "%.03s %s" % (((value*(10**decimals)) / (base ** (i-1))) / (10**decimals) if i > 1 else value, units[base][i-1])

def relativePath(r, var, root, endpoint):
    # remove endpoint, root folder and unquote
    val = r[var].replace(endpoint, "")
    val = val.replace(root, "", 1)
    val = urllib.parse.unquote(val)

    # add leading slash
    sp = val.split('/')
    if 'type' in r and r['type'] == 'd':
        val = "/" + sp[-2]
    elif len(sp) > 1:
        val = "/".join(sp[1:])

    return val

def listToDict(*args):
    return dict(zip(map(str, range(len(*args))), *args))

def getValueByTagReference(v, *args):
    for m in re.findall('@([0-9]+)|@{([\w\.\-]+)}', v):
        rv = m[1] if m[1] > '' else m[0]
        rs = "@%s" % (("{%s}" % m[1]) if m[1] > '' else m[0])
        for d in args:
            ov = getFromDict(d, rv.split('.'))
            if ov:
                break
        if ov is None:
            warning("value reference: tag %s does not exist in provided data" % rs)
        v = v.replace(rs, str(ov)) if ov else v
    return v.replace('@@', '@')

def message(target, msg, msgtype="", color='\x1b[0m', ret=True):
    target.flush()

    frames = inspect.stack()

    try:
        if not options['no-colors']:
            target.write(color)

        target.write('%s:\x1b[0m %s\n' % ("%% %s()" % frames[2][3] if msgtype in ["debug", "verbose"] else msgtype, msg))

        if not options['no-colors']:
            target.write('\x1b[0m')
    finally:
        del frames

    target.flush()

    return ret

def hint(msg, ret=True):
    ''' Print instructions for the user '''

    return message(sys.stdout, msg, "hint", ret=ret)

def error(msg, code=None, ret=False):
    ''' Print error and exit if required '''

    message(sys.stderr, msg, "error", "\x1b[31m")

    if code is not None:
        sys.exit(code)

    return ret

def warning(msg, ret=False):
    ''' Print warning message'''

    if options['quiet']:
        return ret

    return message(sys.stdout, msg, "warning", color="\x1b[96m", ret=ret)

def verbose(msg, ret=True):
    ''' Print verbose text '''

    if not options['verbose']:
        return ret

    return message(sys.stdout, msg, "verbose", '\x1b[33m', ret=ret)

def debug(msg, force=False, ret=True):
    ''' Print debug message'''

    if not options['debug'] and not force:
        return ret

    return message(sys.stdout, msg, "debug", '\x1b[32m', ret=ret)

def note(msg, ret=True):
    ''' Print message'''

    return message(sys.stdout, msg, "note", ret=ret)