#!/usr/bin/env python3

""" Compact OwnCloud/NextCloud WebDAV client
    Author: hevp

    Requires: Python 3
    Packages: see below
"""

import sys, getopt, os, requests, json, cchardet, simplejson, copy, re, urllib, humanize
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
        self.download = {}
        self.success = False

    def run(self, method, path, headers={}, params={}, data="", expectedStatus=SUCCESS, auth=None, quiet=False):
        verbose("Request data: %s" % (data[:250] if type(data) is str else type(data)))
        verbose("Request headers: %s" % simplejson.dumps(headers))

        if self.options['head']:
            method = "HEAD"

        # construct url
        url = self.credentials["hostname"] + self.credentials["endpoint"]
        if not self.options['no-path']:
            url += path

        # construct request
        req = requests.Request(method, url, headers=headers, params=params, data=data, auth=auth)

        self.request = req.prepare()
        self.success = False

        # exit if dry-run
        if self.options['dry-run']:
            warning("dry-run: " + method.upper() + " " + req.url)
            return False

        # some debug messages
        verbose("Options: %s" % self.options)
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
            return self._requestfail() if not quiet else False

        # check if downloading file
        if 'Content-Disposition' in self.response.headers:
            # extract filename
            m = re.match("attachment;.+filename=\"([^\"]+)\"", self.response.headers['Content-Disposition'])
            if not m:
                error("invalid response header disposition value: %s" % self.response.headers['Content-Disposition'], 1)
            else:
                self.download['filename'] = m.group(1)
            # extract checksum if available
            if 'OC-Checksum' in self.response.headers:
                m = re.match("^([^:]+):([0-9a-f]+)$", self.response.headers['OC-Checksum'])
                if m:
                    self.download['checksum'] = {
                        'algorithm': m.group(1),
                        'value': m.group(2)
                    }

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
        debug("response: %s (%s)" % (self.response.reason, self.response.status_code))

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
    def run(self, method, path, headers={}, params={}, data="", expectedStatus=DAVRequest.SUCCESS, quiet=False):
        return DAVRequest.run(self, method, path, headers, params, data, expectedStatus, auth=(self.credentials["user"], self.credentials["token"]), quiet=quiet)


class WebDAVClient(object):
    """ WebDAV client class to set up requests for WebDAV-enabled servers """

    def __init__(self, operation, options):
        self.args = {}
        self.results = None
        self.options = options
        self.headers = {}
        self.operation = None

        # load API definition
        try:
            with open(self.options['api'], "r") as f:
                text = f.read()
            self.api = simplejson.loads(text)

            # post-process API definition
            for o, ov in self.api.items():
                # operation definition completeness test
                missing = ['method', 'description'] - ov.keys()
                if len(missing) > 0:
                    error('missing definition elements for operation \'%s\': \'%s\'' % (o, "\', \'".join(missing)), 1)

                # parsing
                if "parsing" in ov and "variables" in ov["parsing"]:
                    for k, v in ov["parsing"]["variables"].items():
                        if not isinstance(v, dict):
                            ov["parsing"]["variables"][k] = {"xpath": v}

                # ensure options and arguments
                if not "options" in ov:
                    ov["options"] = {}
                if not "arguments" in ov:
                    ov["arguments"] = {"min": 1, "max": 1}

                # set operation-specific option values if operation set
                if o == operation:
                    for (option, value) in ov["options"].items():
                        if not option in self.options:
                            raise Exception("invalid option %s" % option)
                        # alter only if set application option does not differs from default
                        if self.options[option] == common.defaults[option]:
                            self.options[option] = value
        except Exception as e:
            error("api load failed: %s" % e, 1)

    def credentials(self, filename):
        try:
            with open(os.path.abspath(filename), "r") as f:
                text = f.read()
            self.credentials = json.loads(text)
        except Exception as e:
            error("credentials loading failed: %s" % e, 1)

        debug("credentials file \'%s\'" % filename)

        # credentials completeness test
        missing = ['hostname', 'endpoint', 'user', 'token'] - self.credentials.keys()
        if len(missing) > 0:
            error('missing credential elements: %s' % ", ".join(missing), 1)

        return True

    def setargs(self, operation, args):
        # check if valid operation
        if operation not in self.api.keys():
            error("unknown operation \'%s\'" % operation, 1)

        # copy arguments
        self.args = copy.deepcopy(args)

        # set arguments
        self.operation = self.api[operation]
        if "min" in self.operation["arguments"] and "max" in self.operation["arguments"]:
            if len(self.args) < self.operation["arguments"]["min"] or len(self.args) > self.operation["arguments"]["max"]:
                error("incorrect number of arguments", 1)
            # fill missing with None
            for i in range(len(self.args) - 1, self.operation["arguments"]["max"]):
                # try to add default value
                if "defaults" in self.operation and str(i+1) in self.operation["defaults"].keys():
                    self.args.append(self.operation["defaults"][str(i+1)])
                else:
                    self.args.append("")

        # process other arguments
        for k, v in self.operation["arguments"].items():
            if k in ["min", "max"]:
                continue
            # replace reference in argument value
            self.operation["arguments"][k] = self._getArgumentByTagReference(v)

        # make sure a forward slash precedes the path
        self.options["root"] = ("/%s" % self.args[0]).replace('//', '/')
        self.options["target"] = ("/%s" % (self.args[1] if len(self.args) > 1 else "")).replace('//', '/')

        return True

    def run(self):
        """ Perform one of supported actions """

        # disable requests warning if quiet and verification off
        if self.options['no-verify'] and self.options['quiet']:
            requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
            debug('InsecureRequestWarning disabled')

        # start in root path, except if no-path option set
        self.options["source"] = self.options["root"] if not "no-path" in self.operation["options"] or not self.operation["options"]["no-path"] else ""

        # check operation requirements
        if not self.exists() or not self.confirm():
            return False

        # do request
        self.results = self.doRequest(self.options)

        # if boolean false, return
        if self.results == False:
            return False

        # if downloading file and target has been defined
        if "target" in self.operation["arguments"] and self.operation["arguments"]["target"] > "":
            try:
                if os.path.exists(self.operation["arguments"]["target"]) and not self.options["overwrite"]:
                    error("target file %s already exists" % self.operation["arguments"]["target"], 1)
                with open(self.operation["arguments"]["target"], "wb") as f:
                    f.write(self.results.encode('utf-8'))
            except Exception as e:
                error(e, 1)
            self.results = True

        # return immediately if no parsing requested
        if not "parsing" in self.operation or self.options['no-parse']:
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

    def _getArgumentByTagReference(self, v):
        m = re.search('@([0-9]+)', v)
        if not m:
            return v

        for g in m.groups():
            if len(self.args) > int(g):
                v = v.replace("@%s" % g, self.args[int(g)])
            else:
                error("tag reference: argument %s does not exist" % g)

        return v

    def _getXMLTag(self, tag, nsmap):
        if ':' in tag:
            tags = tag.split(':')
            tag = "{%s}%s" % (nsmap[tags[0]], tags[1])
        return tag

    def _getXMLData(self, data, element=None):
        NSMAP = {"d": "DAV:", "oc": "http://owncloud.org/ns", "nc": "http://nextcloud.org/ns"}

        try:
            # create the element itself
            xml = etree.Element(self._getXMLTag(data["root"], NSMAP), nsmap=NSMAP) if element is None else element

            # create any children recursively
            for k, v in (data["elements"].items() if element is None else data.items()):
                sub = etree.SubElement(xml, self._getXMLTag(k, NSMAP), nsmap=NSMAP)
                if type(v) is dict:
                    self._getXMLData(v, sub)
                elif type(v) is list:
                    for l in v:
                        lk = self._getArgumentByTagReference(list(l.keys())[0])
                        lv = self._getArgumentByTagReference(list(l.values())[0])
                        prop = etree.SubElement(sub, self._getXMLTag(lk, NSMAP), nsmap=NSMAP)
                        prop.text = lv
                else:
                    sub.text = v
        except Exception as e:
           error("xml generation failed: %s " % e, 1)

        return etree.tostring(xml).decode('utf-8')

    def doRequest(self, options={}):
        # replace client options by local options
        options = dict(self.options, **options)

        self.request = DAVAuthRequest(self.credentials, options)

        # set request headers if required
        if "headers" in self.operation:
            for h, v in self.operation["headers"].items():
                arg = self._getArgumentByTagReference(v)
                val = self.credentials['hostname'] + self.credentials['endpoint'] + arg if arg else v
                self.headers[h] = val

        # add data to request if required
        data = ""
        if "file" in self.operation["arguments"]:
            # create file upload object and set content type
            data = ChunkedFile(self.operation["arguments"]["file"])
            self.headers['Content-Type'] = 'application/octet-stream'
        elif "data" in self.operation:
            data = self._getXMLData(self.operation["data"])

        # run request, exits early if dry-run
        response = self.request.run(self.operation["method"], options["source"], headers=self.headers, data=data)

        # return if failed
        if not self.request.hassuccess() or response == False:
            return False

        # exit if dry-run
        if self.options['dry-run']:
            return False

        # return immediately without response if no parsing defined
        if "parsing" not in self.operation and not "filename" in self.request.download:
            return True
        # return immediately if no parsing requested
        if self.options['no-parse'] or "filename" in self.request.download:
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
        if self.options['list-empty']:
            results = list(filter(lambda x: x['type'] == 'd' and x['size'] == 0, results))
        # filter dirs (wins) or files
        if self.options['dirs-only']:
            results = list(filter(lambda x: x['type'] == 'd', results))
        elif self.options['files-only']:
            results = list(filter(lambda x: x['type'] == 'f', results))

        return results

    def exists(self):
        if not "exists" in self.operation["options"] or not self.operation["options"]["exists"]:
            return True

        req = DAVAuthRequest(self.credentials, self.options)

        # check if the source path exists
        res = req.run("propfind", self.options["source"], quiet=True)

        if not req.response.status_code in DAVRequest.SUCCESS:
            return error("cannot %s: source path %s does not exist" % (self.operation["method"], self.options["source"]))

        if self.args[1] == "":
            return True

        # check if the target path does not exists
        res = req.run("propfind", self.options["target"], quiet=True)

        if req.response.status_code in DAVRequest.SUCCESS:
            if not self.options['overwrite']:
                return error("cannot %s: target path %s already exists" % (self.operation["method"], self.options["target"]))
            else:
                self.headers['Overwrite'] = 'T'

        return True

    def confirm(self):
        if not "confirm" in self.operation["options"] or not self.operation["options"]["confirm"]:
            return True

        text = "Are you sure you want to %s %s%s (y/n/all/c)? " % (self.operation["method"],
                                                    "%s%s" % ("from " if self.args[1] is not None else "", self.options["source"]),
                                                    " to %s" % self.options["target"] if self.args[1] > "" else "")

        # auto confirm or get input
        if not self.options['confirm']:
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
        for child in res.findall(".//d:%s" % self.operation["parsing"]["items"], nsmap):
            variables = {}
            for var, varv in self.operation["parsing"]["variables"].items():
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
        if 'type' in r and r['type'] == 'd':
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
            kr = k.replace('=', '')
            vr = v.replace(':', '')
            print(("--%-" + maxop + "s %-2s  %s %s") % (kr,
                                                        "-%s" % vr if vr > "" else "",
                                                        ("%s %-" + maxop + "s") % ("Enable" if kr == k else "Set", kr if kr in defaults.keys() else " " * (int(maxop) + 7)),
                                                        "%s(default: %s)" % ("" if kr == k else " " * 3, defaults[kr] if kr in defaults.keys() else "")))
    else:
        # determine required and optional arguments for operation
        args = ""
        for i in range(1, wd.api[operation]['arguments']['max'] + 1):
            args += " %s<arg%d>%s" % ("[" if i > wd.api[operation]['arguments']['min'] else "", i, "]" if i > wd.api[operation]['arguments']['min'] else "")

        # print info and syntax
        print(wd.api[operation]['description'])
        print("\nSyntax: %s %s%s" % (sys.argv[0], operation, args))

        # print description per argument
        if 'descriptions' in wd.api[operation]:
            print("\nArguments:")
            for a,d in wd.api[operation]['descriptions'].items():
                print("  %s: %s" % (int(a)+1,d))

    print()

def main(argv):
    # define quick options, long: short
    quickopts = {"overwrite": "o", "headers": "", "head": "", "no-parse": "", "recursive": "R", "sort": "", "reverse": "r",
                 "dirs-first": "t", "files-only": "f", "dirs-only": "d", "summary": "u", "list-empty": "e", "checksum": "",
                 "human": "h", "confirm": "y", "exists": "", "no-path": "", "verbose": "v", "no-verify": "k",
                 "debug": "", "dry-run": "n", "quiet": "q", "no-colors": "", "api=": "", "credentials=": "c:", "printf=": "p:", "help": "", "version": ""}

    # remove = and : in options
    quickoptsm = dict((k.replace('=',''), v.replace(':','')) for k,v in quickopts.items())

    # assign values to quick options
    common.defaults = dict(common.defaults, **{k: False for k in quickoptsm.keys() if k not in common.defaults})
    common.options = copy.deepcopy(common.defaults)

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
            index = [k for k,v in quickoptsm.items() if v == opt[1:]][0]
            common.options[index] = arg if arg > "" else True

    # create object and read credentials
    wd = WebDAVClient(operation, common.options)

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
            if wd.request.hassuccess() and (wd.results is None or type(wd.results) is bool):
                note("%s successful" % operation)
            else:
                # print out the result, could be XML data
                sys.stdout.write(wd.results)
                sys.stdout.flush()
        else:
            sys.exit(1)

if __name__ == "__main__":
    main(sys.argv[1:])
