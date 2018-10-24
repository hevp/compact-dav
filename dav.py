#!/usr/bin/env python

""" Compact OwnCloud/NextCloud WebDAV client
    Author: hevp

    Requires: Python 3
    Packages: see below
"""

import sys, getopt, os, requests, json, cchardet, simplejson, copy, re, urllib.parse, humanize
from dateutil.parser import parse as dateparse
import common
from common import *

from lxml import etree
from requests.packages.urllib3.exceptions import InsecureRequestWarning


class ChunkedFile(object):
    """ Chunked file upload class to be used with requests package """

    def __init__(self, filename, chunksize=1024*1024*10):
        self.chunksize = chunksize
        try:
            self.obj = open(filename, 'rb')
        except Exception as e:
            error(e, 1)

    def __iter__(self):
        try:
            data = self.obj.read(self.chunksize)
        except Exception as e:
            error(e, 3)

        yield data


class DAVRequest(object):
    """ WebDAV request class for WebDAV-enabled servers """

    SUCCESS = [200, 201, 204, 207]

    def __init__(self, credentials, opts={}):
        self.credentials = credentials
        self.options = opts
        self.result = None
        self.request = None
        self.response = None
        self.success = False

    def run(self, method, path, headers={}, params={}, data="", expectedStatus=SUCCESS, auth=None):
        verbose("request data: %s" % data)
        verbose("request headers: %s" % simplejson.dumps(headers))

        if "head" in self.options and self.options['head']:
            method = "HEAD"

        req = requests.Request(method, self.credentials["hostname"] + self.credentials["endpoint"] + path, headers=headers, params=params, data=data, auth=auth)

        self.request = req.prepare()
        self.success = False

        if self.options['dry-run']:
            print("dry-run: " + method.upper() + " " + req.url)
            return False

        # some debug messages
        verbose("options: %s" % self.options)
        debug(method.upper() + " " + self.request.url)

        # do request
        try:
            s = requests.Session()
            self.response = s.send(self.request, verify=not self.options['no-verify'], timeout=30)
        except requests.exceptions.ReadTimeout as e:
            error("request time out after 30 seconds", 2)
        except requests.exceptions.SSLError as e:
            error(e, 2)

        # determine the encoding of the response text
        if self.response.encoding is None:
            self.response.encoding = cchardet.detect(self.response.content)['encoding']

        # print headers, exit if only head request
        if self.options['headers'] or self.options['head']:
            debug("Response headers: %s" % self.response.headers, True)
            if self.options['head']:
                return False

        # init result
        self.result = self.response.text

        # if failed exit
        if self.response.status_code not in expectedStatus:
            return False #self._requestfail()
        else:
            # parse based on given content type
            if 'Content-Type' in self.response.headers and not self.options['no-parse']:
                info = self.response.headers['Content-Type'].split(';')
                if info[0] == 'application/xml':
                    try:
                        self.result = etree.fromstring(self.result.encode('ascii'))

                    except Exception as e:
                        error("could not decode XML data: %s" % e)
                elif info[0] == 'application/json':
                    try:
                        self.result = simplejson.loads(self.result)
                    except Exception as e:
                        error("could not decode JSON data: %s" % e)

            self.success = True
            debug("Response: %s (%s)" % (self.response.reason, self.response.status_code))

        return self.result

    def hassuccess(self):
        return self.response is not None and self.response.status_code in DAVRequest.SUCCESS

    def _requestfail(self):
        message = ""
        if self.response.status_code >= 400 and self.response.status_code < 500:
            if isinstance(self.result, etree._Element):
                nsmap = {k:v for k,v in self.result.nsmap.items() if k}
                message = self.result.find('.//s:message', nsmap).text

        return error('%s (%s)%s' % (self.response.reason, self.response.status_code, ": %s" % message if message > "" else ""))


class DAVAuthRequest(DAVRequest):
    def run(self, method, path, headers={}, params={}, data="", expectedStatus=DAVRequest.SUCCESS):
        return DAVRequest.run(self, method, path, headers, params, data, expectedStatus, auth=(self.credentials["user"], self.credentials["token"]))


class WebDAVClient(object):
    """ WebDAV client class to set up requests for WebDAV-enabled servers """

    def __init__(self, options):
        self.args = {}
        self.results = None
        self.options = options
        self.headers = {}

        # load API definition
        try:
            with open("webdav.json", "r") as f:
                text = f.read()
            self.api = simplejson.loads(text)

            # post-process API definition
            for o, ov in self.api.items():
                if "parsing" in ov and "variables" in ov["parsing"]:
                    for k, v in ov["parsing"]["variables"].items():
                        if not isinstance(v, dict):
                            ov["parsing"]["variables"][k] = {"xpath": v}
                if not "options" in ov:
                    ov["options"] = {}
                if not "arguments" in ov:
                    ov["arguments"] = {"min": 1, "max": 1}

                # operation definition completeness test
                required = ['method', 'description']
                missing = set(required).difference(set(ov.keys()))
                if len(missing) > 0:
                    error('missing definition elements for operation \'%s\': \'%s\'' % (o, "\', \'".join(missing)), 1)

        except Exception as e:
            error(e, 1)

    def credentials(self, filename):
        try:
            with open(os.path.abspath(filename), "r") as f:
                text = f.read()
            self.credentials = json.loads(text)
        except Exception as e:
            error("credentials loading failed: %s" % e, 1)

        debug("credentials file \'%s\'" % filename)

        # credentials completeness test
        required = ['hostname', 'endpoint', 'user', 'token']
        missing = set(required).difference(set(self.credentials.keys()))
        if len(missing) > 0:
            error('missing credential elements: %s' % ", ".join(missing), 1)

        return True

    def setargs(self, action, args):
        # check if valid action
        if action not in self.api.keys():
            error("unknown action \'%s\'" % action, 1)
        elif "min" in self.api[action]["arguments"] and "max" in self.api[action]["arguments"]:
            if len(args) < self.api[action]["arguments"]["min"] or len(args) > self.api[action]["arguments"]["max"]:
                error("incorrect number of arguments", 1)
            # fill missing with None
            for i in range(len(args) - 1, self.api[action]["arguments"]["max"]):
                args.append(None)

        # set default arguments
        self.action = self.api[action]
        # make sure a forward slash precedes the path
        self.options["root"] = ("/%s" % args[0]).replace('//', '/')
        self.options["target"] = ("/%s" % args[1]).replace('//', '/')

        # copy other arguments
        self.args = copy.deepcopy(args)

        return True

    def run(self):
        """ Perform one of supported actions """

        # disable requests warning if quiet and verification off
        if self.options['no-verify'] and self.options['quiet']:
            requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
            debug('InsecureRequestWarning disabled')

        # start in root path
        self.options["source"] = self.options["root"]

        # check operation requirements
        if not self.exists() or not self.confirm():
            return False

        # do request
        self.results = self.doRequest(self.options)

        # if boolean false, return
        if self.results == False:
            return False

        # return immediately if no parsing requested
        if not "parsing" in self.action or self.options['no-parse']:
            return True

        # show results
        if len(self.results) > 0:
            result = self.printFormat(self.options["printf"], self.results)

            # display summary if requested
            if self.options['summary']:
                result += self.printSummary(self.results)

            self.results = result
        else:
            self.results = "no results"

        return True

    def doRequest(self, options={}):
        # replace client options by local options
        options = {**self.options, **options}

        self.request = DAVAuthRequest(self.credentials, options)

        # set request headers if required
        if "headers" in self.action:
            for h, v in self.action["headers"].items():
                m = re.match('@([0-9]+)', v)
                if m and len(self.args) > int(m.group(1)) - 1:
                    val = self.credentials['hostname'] + self.credentials['endpoint'] + self.args[int(m.group(1))-1]
                else:
                    val = v
                self.headers[h] = val

        # create file upload object if required
        data = ""
        if "file" in self.action["options"]:
            data = ChunkedFile(self.args[1])
            self.headers['Content-Type'] = 'application/octet-stream'

        # run request, exits early if dry-run
        response = self.request.run(self.action["method"], options["source"], headers=self.headers, data=data)

        # return if failed
        if not self.request.hassuccess():
            return False

        # exit if dry-run
        if self.options['dry-run']:
            return False

        # return immediately if no parsing requested
        if "parsing" not in self.action or self.options['no-parse']:
            return response

        # parse request response
        results = self.parse(response, options)

        # recursive processing
        if self.options['recursive']:
            recursiveresults = []
            for l in results:
                if l['type'] == 'd':
                    recursiveresults += self.doRequest({"source": "%s%s" % (options["source"], self.getRelativePath(l, "path"))})
            results += recursiveresults

        # filtering
        if self.options['empty']:
            results = list(filter(lambda x: x['type'] == 'd' and x['size'] == 0, results))
        # filter dirs (wins) or files
        if self.options['dirs-only']:
            results = list(filter(lambda x: x['type'] == 'd', results))
        elif self.options['files-only']:
            results = list(filter(lambda x: x['type'] == 'f', results))

        return results

    def exists(self):
        if not "exists" in self.action["options"] or not self.action["options"]["exists"]:
            return True

        req = DAVAuthRequest(self.credentials, self.options)

        # check if the source path exists
        res = req.run("propfind", self.options["source"])

        if not req.response.status_code in DAVRequest.SUCCESS:
            return error("cannot %s: source path %s does not exist" % (self.action["method"], self.options["source"]))

        if self.args[1] is None:
            return True

        # check if the target path does not exists
        res = req.run("propfind", self.options["target"])

        if req.response.status_code in DAVRequest.SUCCESS:
            if not self.options['overwrite']:
                return error("cannot %s: target path %s already exists" % (self.action["method"], self.options["target"]))
            else:
                self.headers['Overwrite'] = 'T'

        return True

    def confirm(self):
        if not "confirm" in self.action["options"] or not self.action["options"]["confirm"]:
            return True

        text = "Are you sure you want to %s %s%s (y/n/all/c)? " % (self.action["method"],
                                                    "%s%s" % ("from " if self.args[1] is not None else "", self.options["source"]),
                                                    " to %s" % self.options["target"] if self.args[1] is not None else "")

        # auto yes or get input
        if self.options['yes']:
            print("%sy" % text)
        else:
            while True:
                choice = input(text)
                if choice in ['y', 'all']:
                    break
                elif choice in ['n', 'c']:
                    return False

        return True

    def parse(self, res, options):
        # get XML namespace map, excluding default namespace
        nsmap = {k:v for k,v in res.nsmap.items() if k}

        # process result elements
        results = []
        for child in res.findall(".//d:%s" % self.action["parsing"]["items"], nsmap):
            variables = {}
            for var, varv in self.action["parsing"]["variables"].items():
                for paths in varv["xpath"].split('|'):
                    if var in variables:
                        break

                    p = ".//d:" + "/d:".join(paths.split('/'))
                    v = child.find(p, nsmap)

                    # note: booleans are stored invertedly due to sorting algorithm
                    if v is not None and (var not in variables or variables[var] is None):
                        if "type" in varv and varv["type"] == "bool":
                            variables[var] = "0"
                        elif "type" in varv and varv["type"] == "enum":
                            if "values" in varv and "present" in varv["values"]:
                                variables[var] = varv["values"]["present"]
                            else:
                                variables[var] = v.text
                        elif v.text is not None:
                            if "type" in varv and varv["type"] == "int":
                                variables[var] = int(v.text)
                            # treat as string
                            else:
                                variables[var] = v.text
                    elif "type" in varv and varv["type"] == "bool":
                        variables[var] = "1"
                    elif "type" in varv and varv["type"] == "enum":
                        if "values" in varv and "absent" in varv["values"]:
                            variables[var] = varv["values"]["absent"]
                        else:
                            variables[var] = v.text

            # add to results
            results.append(variables)

        # delete first (root) element
        del results[0]

        # apply sorting etc
        sortkey = None
        if options['sort'] and options['dirs-first']:
            sortkey = lambda x: x['type'] + x['path'].lower()
        elif options['sort']:
            sortkey = lambda x: x['path'].lower()
        elif options['dirs-first']:
            sortkey = lambda x: x['type']

        if sortkey is not None:
            results.sort(key=sortkey, reverse=options['reverse'])

        return results

    def getRelativePath(self, r, var):
        # remove endpoint, root folder and unquote
        val = r[var].replace(self.credentials["endpoint"], "")
        val = val.replace(self.options["root"], "", 1)
        val = urllib.parse.unquote(val)

        # add leading slash
        sp = val.split('/')
        if r['type'] == 'd':
            val = "/" + sp[-2]
        elif len(sp) > 1:
            val = "/".join(sp[1:])

        return val

    def printFormat(self, printf, listing):
        printResult = ""

        # find {<varname>:<length>}
        matching = re.findall('{([^}:]+):?([^}]+)?}', printf)

        if not matching:
            return printf

        # copy listing
        results = []

        # loop through result list
        for item in listing:
            if self.options['recursive'] and item['type'] == 'd':
                continue

            # determine and possibly update all found variables
            result = copy.deepcopy(item)
            for var in matching:
                # if found variable exists
                if var[0] in result:
                    # get the original value
                    val = result[var[0]]
                    # special treatment per variable
                    if var[0] == "path":
                        val = self.getRelativePath(result, var[0])
                    elif var[0] == "date":
                        val = dateparse(val).strftime("%Y-%m-%d %H:%M:%S")
                    elif var[0] == "size":
                        val = self.makeHuman(val)
                else:
                    val = "<error>"

                # update temporary result array with sanity check
                result[var[0]] = val if val else ""

            results.append(result)

        # determine maximum lengths of each field when necessary
        maxs = {}
        for var in matching:
            if var[1] > '' and not var[1].isdigit():
                # determine maximum length of all elements for this variable
                # store as string
                lengths = list(map(lambda x: len(x[var[0]]), results))
                maxs[var[0]] = str(max(lengths)) if len(lengths) > 0 else '0'

        # list all elements
        for result in results:
            text = printf

            # determine all variables
            for var in matching:
                val = result[var[0]]

                # justification
                if var[1] > '':
                    if var[1].isdigit():
                        val = ("%" + var[1] + "s") % val
                    elif var[1] == 'l':
                        val = ("%-" + maxs[var[0]] + "s") % val
                    elif var[1] == 'r':
                        val = ("%" + maxs[var[0]] + "s") % val

                # replace variable with value
                text = text.replace("{%s}" % ":".join(filter(lambda x: x>'', list(var))), val)

            # print resulting string
            printResult += "%s\n" % text

        return printResult

    def printSummary(self, listing):
        # filter out any directory if recursive
        res = listing if not self.options['recursive'] else list(filter(lambda x: x['type'] != "d", listing))

        # get total size, directory and file counts
        lsum = sum(map(lambda x: x['size'], res))
        dcount = len(list(filter(lambda x: x['type'] == 'd', res)))
        fcount = len(res) - dcount

        # print total size, file count if > 0, directory count if > 0
        return "%s %s%s%s%s%s\n" % ("\n" if len(listing) > 0 else "",
                                  self.makeHuman(lsum),
                                  " in " if len(listing) > 0 else "",
                                  "%d file%s" % (fcount, "s" if fcount != 1 else "") if fcount > 0 else "",
                                  " and " if (dcount > 0 and fcount > 0) else "",
                                  "%d director%s" % (dcount, "ies" if dcount != 1 else "y") if dcount > 0 else "")

    def makeHuman(self, value, addBytes=False):
        return humanize.naturalsize(value) if self.options['human'] else "%d%s" % (value, " bytes" if addBytes else "")

def usage():
    print("usage: dav.py <operation> <options> <args..>")

def help(wd, operation, options, defaults):
    if operation == "" or operation not in wd.api.keys():
        usage()

        # get maximum length of name of operation
        maxop = str(max(map(lambda x: len(x[0]), wd.api.items())) + 2)
        # print operations
        print("\nOperations:")
        for o, ov in wd.api.items():
            print(("%-" + maxop + "s %s") % (o, ov["description"]))

        # get maximum length of name of options
        maxop = str(max(map(lambda x: len(x[0]), options.items())))
        # print options
        print("\nOptions:")
        for k, v in options.items():
            k = k.replace('=', '')
            v = v.replace(':', '')
            print(("--%-" + maxop + "s %-2s  %s %s") % (k.replace("=", ""),
                                                        "-%s" % v if v > "" else "",
                                                        ("Enable %-" + maxop + "s") % k if k in defaults.keys() else " " * (int(maxop) + 7),
                                                        "(default: %s)" % defaults[k] if k in defaults.keys() else ""))
    else:
        action = wd.api[operation]

        # determine required and optional arguments for operation
        args = ""
        for i in range(1, action['arguments']['max'] + 1):
            args += " %s<arg%d>%s" % ("[" if i > action['arguments']['min'] else "", i, "]" if i > action['arguments']['min'] else "")

        # print info and syntax
        print(action['description'])
        print("\nSyntax: %s %s%s" % (sys.argv[0], operation, args))

        # print description per argument
        if 'descriptions' in action:
            print("\nArguments:")
            for a,d in action['descriptions'].items():
                print("  %s: %s" % (int(a)+1,d))

    print()

def main(argv):
    # define quick options, long: short
    quickopts = {"overwrite": "o", "headers": "", "head": "", "no-parse": "", "recursive": "R", "sort": "", "reverse": "r",
                 "dirs-first": "t", "files-only": "f", "dirs-only": "d", "summary": "u", "verbose": "v", "no-verify": "k", "debug": "", "dry-run": "n", "human": "h", "yes": "y",
                 "quiet": "q", "no-colors": "", "empty": "e", "credentials=": "c:", "printf=": "p:", "help": "", "version": ""}

    # remove = and : in options
    quickoptsm = dict((k.replace('=',''), v.replace(':','')) for k,v in quickopts.items())

    # assign values to quick options
    common.defaults = {**common.defaults, **{k: False for k in quickoptsm.keys() if k not in common.defaults}}
    common.options = copy.deepcopy(common.defaults)

    # handle arguments
    try:
        opts, args = getopt.gnu_getopt(argv,
                                       "".join(list(filter(lambda x: x > "", quickopts.values()))),
                                       list(quickopts.keys()))
    except getopt.GetoptError as e:
        error(e, 1)

    # create object and read credentials
    wd = WebDAVClient(common.options)

    # set operation
    operation = args[0] if len(args) > 0 else ""

    # parse options and arguments
    for opt, arg in opts:
        if opt[2:] in quickoptsm.keys():
            common.options[opt[2:]] = arg if arg > "" else True
        elif opt[1:] in quickoptsm.values():
            index = [k for k,v in quickoptsm.items() if v == opt[1:]][0]
            common.options[index] = arg if arg > "" else True

    if common.options['help']:
        help(wd, operation, quickopts, common.defaults)
        sys.exit(0)
    elif common.options['version']:
        print("%s %s" % (TITLE, VERSION))
        sys.exit(0)

    # check operation
    if operation == "":
        usage()
        sys.exit(1)

    # init operation
    if wd.setargs(operation, args[1:]):
        # load credentials
        if not wd.credentials(common.options['credentials']):
            sys.exit(1)

        # get result and print
        res = wd.run()

        # if there is a result, print it
        if res:
            if wd.request.hassuccess() and not wd.results:
                note("%s successful" % operation)
            else:
                # print out the result, could be XML data
                sys.stdout.write(wd.results)
                sys.stdout.flush()
        else:
            sys.exit(1)

if __name__ == "__main__":
    main(sys.argv[1:])
