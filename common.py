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

def getArgumentByTagReference(data, v):
    m = re.search('@([0-9]+)', v)
    if not m:
        return v

    for g in m.groups():
        if len(data) > int(g):
            v = v.replace("@%s" % g, data[int(g)])
        else:
            error("tag reference: argument %s does not exist" % g)

    return v

def message(target, msg, msgtype="", color='\x1b[0m'):
    target.flush()

    frames = inspect.stack()

    try:
        if not options['no-colors']:
            target.write(color)

        target.write('%s:\x1b[0m %s\n' % ("%% %s()" % frames[2][3] if msgtype == "" else msgtype, msg))

        if not options['no-colors']:
            target.write('\x1b[0m')
    finally:
        del frames

    target.flush()

def hint(msg):
    ''' Print instructions for the user '''

    message(sys.stdout, msg, "hint")

def error(msg, code=None):
    ''' Print error and exit if required '''

    message(sys.stderr, msg, "error", "\x1b[31m")

    if code is not None:
        sys.exit(code)

    return False

def warning(msg):
    ''' Print warning message'''

    message(sys.stdout, msg, "warning")

def verbose(msg):
    ''' Print verbose text '''

    if not options['verbose']:
        return

    message(sys.stdout, msg, "", '\x1b[33m')

def debug(msg, force=False):
    ''' Print debug message'''

    if not options['debug'] and not force:
        return

    message(sys.stdout, msg, "", '\x1b[32m')

def note(msg):
    ''' Print message'''

    message(sys.stdout, msg, "note")
