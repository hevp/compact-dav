import copy
import os
import re
import requests
import simplejson

from lxml import etree
from urllib3.exceptions import InsecureRequestWarning

from common import error, debug, verbose, getValueByTagReference, listToDict, relativePath
from generator import GeneratorFactory
from parser import ParserFactory
from request import DAVAuthRequest, DAVRequest

class ChunkedFile():
    """ Chunked file upload class to be used with requests package """

    def __init__(self, filename, chunksize=1024*1024*10):
        self.chunksize = chunksize
        try:
            self.obj = open(filename, 'rb')
            self.size = os.path.getsize(filename)
        except Exception as e:
            error(e, 1)

    def __iter__(self):
        try:
            for data in self.obj.read(self.chunksize):
                yield data
        except Exception as e:
            error(e, 3)

    def __len__(self):
        return self.size


class WebDAVClient():
    """ WebDAV client class to set up requests for WebDAV-enabled servers """

    def __init__(self, options):
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
                missing = set(['method', 'description']) - set(ov.keys())
                if len(missing) > 0:
                    error(f"missing definition elements for operation '{o}': {', '.join(missing)}", 1)

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
                            raise Exception(f"invalid option {option}")
                        # alter only if set application option does not differs from default
                        if self.options[option] == self.options["defaults"][option]:
                            self.options[option] = value
        except Exception as e:
            error(f"api load failed: {e}", 1)

    def credentials(self, filename):
        try:
            with open(os.path.abspath(filename), "r") as f:
                text = f.read()
            self.options["credentials"] = simplejson.loads(text)
        except Exception as e:
            error(f"credentials loading failed: {e}", 1)

        debug(f"credentials file '{filename}'")

        # credentials completeness test
        required = ['hostname', 'endpoint', 'user', 'token']
        missing = set(required) - set(self.options["credentials"].keys())
        if len(missing) > 0:
            error(f"missing credential elements: {', '.join(missing)}", 1)

        self.options["credentials"]["domain"] = re.sub(r'https?://(.*)', '\\1', self.options["credentials"]["hostname"])

        # apply any other settings
        self.options.update({x: self.options["credentials"][x] for x in self.options["credentials"].keys() - required})

        verbose(self.options["credentials"])

        return True

    def setargs(self, operation, args):
        # check if valid operation
        if operation not in self.api.keys():
            error(f"unknown operation '{operation}'", 1)

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
        self.options["root"] = (f"/{self.args[0]}").replace('//', '/')
        self.options["target"] = (f"/{self.args[1] if len(self.args) > 1 else ''}").replace('//', '/')

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
                    error(f"target file {self.defs['arguments']['target']} already exists", 1)
                with open(self.defs["arguments"]["target"], "wb") as f:
                    f.write(self.request.response.content)
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
        if not self.request.hassuccess() or response is None:
            return error(f"{self.request.response.status_code} {self.request.response.reason}")

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
                    recursiveresults += self.doRequest({"source": f"{self.options['source']}{relativePath(res, 'path')}"})
            results += recursiveresults

        return results

    def exists(self):
        if "exists" not in self.defs["options"] or not self.defs["options"]["exists"]:
            return True

        req = DAVAuthRequest(self.options)

        # check if the source path exists
        req.run("propfind", self.options["source"], quiet=True)

        if req.response.status_code not in DAVRequest.SUCCESS:
            return error(f"cannot {self.defs['method']}: source path {self.options['source']} does not exist")

        if self.args[1] == "":
            return True

        # check if the target path does not exists
        req.run("propfind", self.options["target"], quiet=True)

        if req.response.status_code in DAVRequest.SUCCESS:
            if not self.options['overwrite']:
                return error(f"cannot {self.defs['method']}: target path {self.options['target']} already exists")
            else:
                self.headers['Overwrite'] = 'T'

        return True

    def confirm(self):
        if "confirm" not in self.defs["options"] or not self.defs["options"]["confirm"]:
            return True

        from_str = "from " if self.args[1] is not None else ""
        to_str = f" to {self.options['target']}" if self.args[1] > "" else ""
        text = f"Are you sure you want to {self.defs['method']} {from_str}{self.options['source']}{to_str} (y/n/all/c)? "

        # auto confirm or get input
        if not self.options['confirm']:
            print(f"{text}y")
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
                return etree.tostring(self.results).decode('utf-8')
            elif type(self.results) is dict:
                return simplejson.dumps(self.results)

        return self.results if isinstance(self.results, str) else f"{self.results}"
