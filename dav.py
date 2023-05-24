#!/usr/bin/env python3

""" Compact OwnCloud/NextCloud WebDAV client
    Author: hevp

    Requires: Python 3
    Packages: see requirements.txt
"""

import sys, getopt, copy

from client import WebDAVClient
import common
from common import error, note


TITLE = "CompactDAV"
VERSION = "1.1"


class ClientOptions(dict):
    def __init__(self, options, defaults):
        self.update(options)
        self["defaults"] = defaults
        self["credentials"] = None


def version():
    print("%s version %s" % (TITLE, VERSION))


def usage():
    print("usage: dav.py <operation> <options> <args..>")


def help(wd, operation, quickopts):
    if operation == "" or operation not in wd.api.keys():
        version()
        usage()

        # get maximum length of name of operation
        maxop = str(max(map(lambda x: len(x[0]), wd.api.items())) + 2)
        # print operations
        print("\nOperations:")
        for o, ov in wd.api.items():
            print(("%-" + maxop + "s %s") % (o, ov["description"]))

        # get maximum length of name of options, and value
        maxopk = str(max(map(lambda x: len(x), wd.options.keys())))
        # print options
        print("\nOptions:")
        for k, v in quickopts.items():
            kr = k.replace('=', '')
            print(("%s --%-" + maxopk + "s  %s %s") % ("-%s " % v[0] if v else "   ",
                  kr,
                  ("%s %-" + maxopk + "s") % ("Enable" if kr == k else "Set", kr if kr in wd.options["defaults"].keys() else " " * (int(maxopk) + 7)),
                  "%s(default: '%s')" % ("" if kr == k else " " * 3, wd.options["defaults"][kr] if kr in wd.options["defaults"].keys() else "")))
    else:
        # determine required and optional arguments for operation
        args = ""
        for i in range(1, wd.api[operation]['arguments']['max'] + 1):
            args += " %s<arg%d>%s" % ("[" if i > wd.api[operation]['arguments']['min'] else "", i, "]" if i > wd.api[operation]['arguments']['min'] else "")

        # print info and syntax
        print(wd.api[operation]['description'])
        print("\nSyntax: %s %s%s%s" % (sys.argv[0], "[options] " if len(wd.api[operation]['options']) else "", operation, args))

        # print description per argument
        if 'descriptions' in wd.api[operation]:
            print("\nArguments:")
            for a, d in filter(lambda x: x[0].isdigit(), wd.api[operation]['descriptions'].items()):
                print(f"  {int(a) + 1}: {d}")
            if len(wd.api[operation]['options']):
                print("\nOptions:")
                maxopk = str(max(map(lambda x: len(x), wd.api[operation]['descriptions'].keys())))
                maxopv = str(max(map(lambda x: len(x), wd.api[operation]['descriptions'].values())))
                for a, d in filter(lambda x: not x[0].isdigit(), wd.api[operation]['descriptions'].items()):
                    print(("  --%-" + maxopk + "s  %-" + maxopv + "s  (default: '%s')") % (a, d, wd.options[a]))

    print()


def main(argv):
    # default values for options
    defaults = {
        "api": "webdav.json",
        "credentials-file": "credentials.json",
        "printf": "{date} {size:r} {path}",
        "timeout": 86400
    }

    # define quick options, long: short
    quickopts = {"overwrite": "o", "headers": "", "head": "", "no-parse": "", "recursive": "R", "sort": "", "reverse": "r",
                 "dirs-first": "t", "files-only": "f", "dirs-only": "d", "summary": "u", "list-empty": "e", "checksum": "",
                 "human": "h", "confirm": "y", "exists": "", "no-path": "", "verbose": "v", "no-verify": "k", "hide-root": "",
                 "debug": "", "dry-run": "n", "quiet": "q", "no-colors": "", "api=": "", "credentials-file=": "c:", "printf=": "p:", "help": "", "version": ""}

    # remove = and : in options
    quickoptsm = dict((k.replace('=', ''), v.replace(':', '')) for k, v in quickopts.items())

    # assign values to quick options
    defaults = dict(defaults, **{k: False for k in quickoptsm.keys() if k not in defaults})
    common.options = ClientOptions(copy.deepcopy(defaults), copy.deepcopy(defaults))

    # handle arguments
    try:
        opts, args = getopt.gnu_getopt(argv,
                                       "".join(list(filter(lambda x: x > "", quickopts.values()))),
                                       list(quickopts.keys()))
    except getopt.GetoptError as e:
        error(e, 1)

    # set operation
    operation = args[0] if len(args) > 0 else ""

    # parse options and arguments
    for opt, arg in opts:
        if opt[2:] in quickoptsm.keys():
            common.options[opt[2:]] = arg if arg > "" else True
        elif opt[1:] in quickoptsm.values():
            index = [k for k, v in quickoptsm.items() if v == opt[1:]][0]
            common.options[index] = arg if arg > "" else True

    # create object and read credentials
    wd = WebDAVClient(common.options)

    if common.options['help']:
        help(wd, operation, quickopts)
        sys.exit(0)
    elif common.options['version']:
        version()
        sys.exit(0)

    # check operation
    if operation == "":
        usage()
        sys.exit(1)

    # init operation and credentials
    if not wd.setargs(operation, args[1:]) or \
       not wd.credentials(common.options['credentials-file']):
        sys.exit(1)

    # get result and print
    if common.options['debug']:
        res = wd.run()
    else:
        try:
            res = wd.run()
        except Exception as e:
            print(f"error: {e}")
            sys.exit()

    # if there is a result, print it
    if res and wd.request.hassuccess():
        if wd.results is None or type(wd.results) is bool:
            note("%s successful" % operation)
        else:
            # print out the result, could be XML data
            sys.stdout.write(wd.format())
            sys.stdout.flush()
    else:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
