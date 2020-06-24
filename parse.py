""" Compact OwnCloud/NextCloud WebDAV client parse classes
    Author: hevp
"""

from common import *
import copy
from lxml import etree
from dateutil.parser import parse as dateparse

class ParserFactory():
    @staticmethod
    def getParser(p, data, options):
        if p.get('scope', '') == 'headers':
            parser = HeadersParser(p, options)
        elif p.get('scope', '') == 'response':
            if type(data) is etree._Element:
                if options["operation"] == 'list':
                    parser = ListXMLResponseParser(p, options)
                else:
                    parser = XMLResponseParser(p, options)
            elif type(data) is dict:
                parser = JSONResponseParser(p, options)
            else:
                parse = ResponseParser(p, options)
        else:
            parser = Parser(p, options)

        return parser.run(data)

class Parser(dict):
    def __init__(self, defs, options={}, resultInit=None):
        self.update(defs)
        self.options = options
        self.result = resultInit

    def _pre(self, data):
        pass

    def _parse(self, data):
        pass

    def _post(self, data):
        pass

    def run(self, data):
        self._pre(data)
        self._parse(data)
        self._post(data)

        return self

    def result(self):
        return self.result

    def filter(self):
        pass

    def format(self):
        return copy.deepcopy(self.result)

class HeadersParser(Parser):
    pass

class ResponseParser(Parser):
    pass

class XMLResponseParser(ResponseParser):
    def __init__(self, data, options={}):
        super().__init__(data, options, [])

    def _parse(self, data):
        super()._parse(data)
        # get XML namespace map, excluding default namespace
        nsmap = {k:v for k,v in data.nsmap.items() if k}

        # process result elements
        for child in data.findall(".//d:%s" % self["items"], nsmap):
            variables = {}
            for var, varv in self["variables"].items():
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
            self.result.append(variables)

    def _post(self, data):
        # apply sorting etc
        sortkey = None
        if self.options['sort'] and self.options['dirs-first']:
            sortkey = lambda x: x['type'] + x['path'].lower()
        elif self.options['sort']:
            sortkey = lambda x: x['path'].lower()
        elif self.options['dirs-first']:
            sortkey = lambda x: x['type']

        if sortkey is not None:
            self.result.sort(key=sortkey, reverse=self.options['reverse'])

        if self.options['hide-root'] and len(self.result):
            self.result = self.result[1:]


class ListXMLResponseParser(XMLResponseParser):
    def _post(self, data):
        super()._post(data)

        # filtering
        if self.options['list-empty']:
            self.result = list(filter(lambda x: x['type'] == 'd' and x['size'] == 0, self.result))
        # filter dirs (wins) or files
        if self.options['dirs-only']:
            self.result = list(filter(lambda x: x['type'] == 'd', self.result))
        elif self.options['files-only']:
            self.result = list(filter(lambda x: x['type'] == 'f', self.result))

    def format(self):
        printResult = ""
        printf = self.options.get("printf", "")

        # find {<varname>:<length>}
        matching = re.findall('{([^}:]+):?([^}]+)?}', printf)

        if not matching:
            return printf

        # loop through result list
        results = []
        for item in self.result:
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
                        val = relativePath(result, var[0], self.options["root"], self.options["credentials"]["endpoint"])
                    elif var[0] == "date":
                        val = dateparse(val).strftime("%Y-%m-%d %H:%M:%S")
                    elif var[0] == "size":
                        val = makeHuman(val)
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

    def format_summary(self):
        # filter out any directory if recursive
        res = copy.deepcopy(self.result) if not self.options['recursive'] else list(filter(lambda x: x['type'] != "d", self.result))

        # get total size, directory and file counts
        lsum = sum(map(lambda x: x['size'], res))
        dcount = len(list(filter(lambda x: x['type'] == 'd', res)))
        fcount = len(res) - dcount

        # print total size, file count if > 0, directory count if > 0
        return "%s %s%s%s%s%s\n" % ("\n" if len(self.result) > 0 else "",
                                  makeHuman(lsum, len(self.result)),
                                  " in " if len(self.result) > 0 else "",
                                  "%d file%s" % (fcount, "s" if fcount != 1 else "") if fcount > 0 else "",
                                  " and " if (dcount > 0 and fcount > 0) else "",
                                  "%d director%s" % (dcount, "ies" if dcount != 1 else "y") if dcount > 0 else "")


class JSONResponseParser(ResponseParser):
    pass
