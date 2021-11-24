#!/usr/bin/env python3

""" Compact OwnCloud/NextCloud WebDAV client
    Author: hevp

    Requires: Python 3
    Packages: see below
"""

import sys, getopt, os, requests, json, cchardet, simplejson, copy, re
import common
from common import debug, error, verbose, warning, note, getValueByTagReference, listToDict
from parse import ParserFactory
from generate import GeneratorFactory

from lxml import etree
from requests.packages.urllib3.exceptions import InsecureRequestWarning

TITLE = "CompactDAV"
VERSION = "1.1"


class ClientOptions(dict):
    def __init__(self, options, defaults):
        self.update(options)
        self["defaults"] = defaults
        self["credentials"] = None


class ChunkedFile():
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


class DAVRequest():
    """ WebDAV request class for WebDAV-enabled servers """

    SUCCESS = [200, 201, 204, 207]

    def __init__(self, options={}):
        self.options = options
        self.result = None
        self.request = None
        self.response = None
        self.download = {}
        self.success = False

    def run(self, method, path, headers={}, params={}, data="", expectedStatus=SUCCESS, auth=None, quiet=False):
        verbose("Request data: %s" % (data[:1000] if type(data) is str else type(data)))

        if self.options['head']:
            method = "HEAD"

        # construct url
        url = self.options["credentials"]["hostname"] + self.options["credentials"]["endpoint"]
        if not self.options['no-path']:
            url += path

        # construct request
        req = requests.Request(method, url, headers=headers, params=params, data=data, auth=auth)

        self.request = req.prepare()
        self.success = False

        verbose("Request headers: %s" % self.request.headers)

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
        except requests.exceptions.ReadTimeout:
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

        debug("Response: %s %s" % (self.response.status_code, self.response.reason))
        verbose("Response: %s" % self.response.text)

        # init result
        self.result = self.response.text

        # if failed exit
        if self.response.status_code not in expectedStatus:
            return self.result  # self._requestfail() if not quiet else False

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

        return self.result

    def hassuccess(self):
        return self.response is not None and self.response.status_code in DAVRequest.SUCCESS

    def _requestfail(self):
        message = ""
        if self.response.status_code >= 400 and self.response.status_code < 500:
            if isinstance(self.result, etree._Element):
                nsmap = {k: v for k, v in self.result.nsmap.items() if k}
                message = self.result.find('.//s:message', nsmap).text

        return error('%s (%s)%s' % (self.response.reason, self.response.status_code, ": %s" % message if message > "" else ""))


class DAVAuthRequest(DAVRequest):
    def run(self, method, path, headers={}, params={}, data="", expectedStatus=DAVRequest.SUCCESS, quiet=False):
        return DAVRequest.run(self, method, path, headers, params, data, expectedStatus,
                              auth=(self.options["credentials"]["user"], self.options["credentials"]["token"]) if 'Authorization' not in headers else None,
                              quiet=quiet)


class WebDAVClient():
    """ WebDAV client class to set up requests for WebDAV-enabled servers """

    def __init__(self, operation, options):
        self.args = {}
        self.results = None
        self.options = options
        self.headers = {}
        self.operation = None

        self._loadapi()

    def _loadapi(self):
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
                if "options" not in ov:
                    ov["options"] = {}
                if "arguments" not in ov:
                    ov["arguments"] = {"min": 1, "max": 1}

                # set operation-specific option values if operation set
                if o == self.operation:
                    for (option, value) in ov["options"].items():
                        if option not in self.options:
                            raise Exception("invalid option %s" % option)
                        # alter only if set application option does not differs from default
                        if self.options[option] == self.options["defaults"][option]:
                            self.options[option] = value
        except Exception as e:
            error("api load failed: %s" % e, 1)

    def credentials(self, filename):
        try:
            with open(os.path.abspath(filename), "r") as f:
                text = f.read()
            self.options["credentials"] = json.loads(text)
        except Exception as e:
            error("credentials loading failed: %s" % e, 1)

        debug("credentials file \'%s\'" % filename)

        # credentials completeness test
        required = ['hostname', 'endpoint', 'user', 'token']
        missing = required - self.options["credentials"].keys()
        if len(missing) > 0:
            error('missing credential elements: %s' % ", ".join(missing), 1)

        self.options["credentials"]["domain"] = re.sub('https?://(.*)', '\\1', self.options["credentials"]["hostname"])

        # apply any other settings
        self.options.update({x: self.options["credentials"][x] for x in self.options["credentials"].keys() - required})

        verbose(self.options["credentials"])

        return True

    def setargs(self, operation, args):
        # check if valid operation
        if operation not in self.api.keys():
            error("unknown operation \'%s\'" % operation, 1)

        # copy arguments
        self.options["operation"] = operation
        self.args = copy.deepcopy(args)

        # set arguments
        self.defs = self.api[operation]
        if "min" in self.defs["arguments"] and "max" in self.defs["arguments"]:
            if len(self.args) < self.defs["arguments"]["min"] or len(self.args) > self.defs["arguments"]["max"]:
                error("incorrect number of arguments", 1)
            # fill missing with None
            for i in range(len(self.args) - 1, self.defs["arguments"]["max"]):
                # try to add default value
                if "defaults" in self.defs and str(i+1) in self.defs["defaults"].keys():
                    self.args.append(self.defs["defaults"][str(i+1)])
                else:
                    self.args.append("")

        # process arguments other than min, max
        for k, v in filter(lambda x: not x[0] in ["min", "max"], self.defs["arguments"].items()):
            # replace reference in argument value
            self.defs["arguments"][k] = getValueByTagReference(v, listToDict(self.args))

        # make sure a forward slash precedes the path
        self.options["root"] = ("/%s" % self.args[0]).replace('//', '/')
        self.options["target"] = ("/%s" % (self.args[1] if len(self.args) > 1 else "")).replace('//', '/')

        return True

    def run(self):
        """ Perform one of supported actions """

        # disable requests warning if quiet and verification off
        if self.options['no-verify']:
            requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
            if self.options['quiet']:
                debug('InsecureRequestWarning disabled')

        # start in root path, except if no-path option set
        self.options["source"] = self.options["root"] if "no-path" not in self.defs["options"] or not self.defs["options"]["no-path"] else ""

        # check operation requirements
        if not self.exists() or not self.confirm():
            return False

        # do request
        self.results = self.doRequest(self.options)

        # if boolean false, return
        if not self.results:
            return False

        # if downloading file and target has been defined
        if "target" in self.defs["arguments"] and self.defs["arguments"]["target"] > "":
            try:
                if os.path.exists(self.defs["arguments"]["target"]) and not self.options["overwrite"]:
                    error("target file %s already exists" % self.defs["arguments"]["target"], 1)
                with open(self.defs["arguments"]["target"], "wb") as f:
                    f.write(self.results.encode('utf-8'))
            except Exception as e:
                error(e, 1)
            self.results = True

        # return immediately if no parsing requested
        if "parsing" not in self.defs or self.options['no-parse']:
            return True

        # show results
        if len(self.results) > 0:
            result = None
            for r in self.results:
                if not r['scope'] == 'response':
                    continue
                result = r.format()

                # display summary if requested
                if self.options['summary']:
                    result += r.format_summary()

            self.results = result if result else self.results
        else:
            self.results = "no results"

        return True

    def setHeader(self, tag, value):
        if type(value) is dict:
            # conditional headers to be implemented
            pass
        else:
            self.headers[tag] = getValueByTagReference(value, listToDict(self.args), self.options)

    def doRequest(self, options={}):
        # replace client options by local options
        opts = copy.deepcopy(self.options)
        opts.update(options)

        self.request = DAVAuthRequest(options)

        # set request headers if required
        if "headers" in self.defs:
            for h, v in self.defs["headers"].items():
                self.setHeader(h, v)

        # add data to request if required
        data = ""
        if "file" in self.defs["arguments"]:
            # create file upload object and set content type
            data = ChunkedFile(self.defs["arguments"]["file"])
            self.headers['Content-Type'] = 'application/octet-stream'
        elif "data" in self.defs:
            gen = GeneratorFactory.getGenerator(self.defs["data"], self.options)
            data = gen.generate(self.defs["data"])
            self.headers['Content-Type'] = gen.getContentType()

        # run request, exits early if dry-run
        response = self.request.run(self.defs["method"], opts["source"], headers=self.headers, data=data)

        # return if failed
        if not self.request.hassuccess() or not response:
            print("TEST")
            return False

        # exit if dry-run
        if opts['dry-run']:
            return False

        # return immediately without response if no parsing defined
        if "parsing" not in self.defs and "filename" not in self.request.download:
            return True
        # return immediately if no parsing requested
        if opts['no-parse'] or "filename" in self.request.download:
            return response

        # parse request response
        results = self.parse(response, opts)

        # recursive processing
        if self.options['recursive']:
            recursiveresults = []
            for res in [r for r in results if r['scope'] == 'response']:
                if res['type'] == 'd':
                    recursiveresults += self.doRequest({"source": "%s%s" % (self.options["source"], self.getRelativePath(res, "path"))})
            results += recursiveresults

        return results

    def exists(self):
        if "exists" not in self.defs["options"] or not self.defs["options"]["exists"]:
            return True

        req = DAVAuthRequest(self.options)

        # check if the source path exists
        req.run("propfind", self.options["source"], quiet=True)

        if req.response.status_code not in DAVRequest.SUCCESS:
            return error("cannot %s: source path %s does not exist" % (self.defs["method"], self.options["source"]))

        if self.args[1] == "":
            return True

        # check if the target path does not exists
        req.run("propfind", self.options["target"], quiet=True)

        if req.response.status_code in DAVRequest.SUCCESS:
            if not self.options['overwrite']:
                return error("cannot %s: target path %s already exists" % (self.defs["method"], self.options["target"]))
            else:
                self.headers['Overwrite'] = 'T'

        return True

    def confirm(self):
        if "confirm" not in self.defs["options"] or not self.defs["options"]["confirm"]:
            return True

        text = "Are you sure you want to %s %s%s (y/n/all/c)? " % (self.defs["method"],
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

    def parse(self, data, options):
        return list(map(lambda p: ParserFactory.getParser(p, data, options), self.defs.get('parsing', [])))

    def format(self):
        """ Format the result of the request """

        if self.options['human']:
            if type(self.results) is etree._Element:
                return etree.tostring(self.results, pretty_print=True).decode('utf-8')
            elif type(self.results) is dict:
                return simplejson.dumps(self.results, indent=4)

        return self.results


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
                print("  %s: %s" % (int(a) + 1, d))
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
    wd = WebDAVClient(operation, common.options)

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
    res = wd.run()

    # if there is a result, print it
    if res:
        if wd.request.hassuccess() and (wd.results is None or type(wd.results) is bool):
            note("%s successful" % operation)
        else:
            # print out the result, could be XML data
            sys.stdout.write(wd.format())
            sys.stdout.flush()
    else:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
