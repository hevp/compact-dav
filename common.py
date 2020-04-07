#!/usr/bin/env python

import sys, inspect

# current options global
options = {}

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
