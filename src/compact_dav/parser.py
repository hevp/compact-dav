""" Compact OwnCloud/NextCloud WebDAV client parse classes
    Author: hevp
"""

import re
import copy

from lxml import etree
from dateutil.parser import parse as dateparse

from .common import makeHuman, relativePath


class ParserFactory():
    @staticmethod
    def getParser(p: dict, data: object, options: dict) -> "Parser":
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
                parser = ResponseParser(p, options)
        else:
            parser = Parser(p, options)

        return parser.run(data)


class Parser(dict):
    def __init__(self, defs: dict, options: dict = {}, resultInit: object = None) -> None:
        self.update(defs)
        self.options = options
        self._result = resultInit

    def _pre(self, data: object) -> None:
        pass

    def _parse(self, data: object) -> None:
        pass

    def _post(self, data: object) -> None:
        pass

    def run(self, data: object) -> "Parser":
        self._pre(data)
        self._parse(data)
        self._post(data)

        return self

    def result(self) -> object:
        return self._result

    def filter(self) -> None:
        pass

    def format(self) -> object:
        return copy.deepcopy(self._result)


class HeadersParser(Parser):
    pass


class ResponseParser(Parser):
    pass


class XMLResponseParser(ResponseParser):
    def __init__(self, data: dict, options: dict = {}) -> None:
        super().__init__(data, options, [])

    def _parse(self, data: etree._Element) -> None:
        super()._parse(data)
        # get XML namespace map, excluding default namespace
        nsmap = {k: v for k, v in data.nsmap.items() if k}
        # get main namespace from root element
        ns = data.prefix

        # process result elements
        for child in data.findall(f".//{ns}:{self['items']}", nsmap):
            variables = {}

            for var, varv in self["variables"].items():
                for paths in varv["xpath"].split('|'):
                    if var in variables:
                        break

                    p = f".//{ns}:{f'/{ns}:'.join(paths.split('/'))}"
                    v = child.find(p, nsmap)

                    # note: booleans are stored invertedly due to sorting algorithm
                    if v is not None:
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
            self._result.append(variables)

    def _post(self, data: etree._Element) -> None:
        # apply sorting etc
        if self.options['sort'] and self.options['dirs-first']:
            self._result.sort(key=lambda x: x['type'] + x['path'].lower(), reverse=self.options['reverse'])
        elif self.options['sort']:
            self._result.sort(key=lambda x: x['path'].lower(), reverse=self.options['reverse'])
        elif self.options['dirs-first']:
            self._result.sort(key=lambda x: x['type'], reverse=self.options['reverse'])

        if self.options['hide-root'] and len(self._result):
            self._result = self._result[1:]


class ListXMLResponseParser(XMLResponseParser):
    def _post(self, data: etree._Element) -> None:
        super()._post(data)

        # filtering
        if self.options['list-empty']:
            self._result = [x for x in self._result if x['type'] == 'd' or x['size'] == 0]
        # filter dirs (wins) or files
        if self.options['dirs-only']:
            self._result = [x for x in self._result if x['type'] == 'd']
        elif self.options['files-only']:
            self._result = [x for x in self._result if x['type'] == 'f']

    def format(self) -> str:
        printResult = ""
        printf = self.options.get("printf", "")

        # find {<varname>:<length>}
        matching = re.findall(r'{([^}:]+):?([^}]+)?}', printf)

        if not matching:
            return printf

        # loop through result list
        results = []
        for item in self._result:
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
                    val = None

                # update temporary result array with sanity check
                result[var[0]] = val if val else ""

            results.append(result)

        # determine maximum lengths of each field when necessary
        maxs = {}
        for var in matching:
            if var[1] > '' and not var[1].isdigit():
                # determine maximum length of all elements for this variable
                # store as string
                lengths = [len(x[var[0]]) for x in results]
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
                        val = f"{val:>{var[1]}}"
                    elif var[1] == 'l':
                        val = f"{val:<{maxs[var[0]]}}"
                    elif var[1] == 'r':
                        val = f"{val:>{maxs[var[0]]}}"

                # replace variable with value
                text = text.replace(f"{{{':'.join(v for v in var if v)}}}", val)

            # print resulting string
            printResult += f"{text}\n"

        return printResult

    def format_summary(self) -> str:
        # filter out any directory if recursive
        res = copy.deepcopy(self._result) if not self.options['recursive'] else [x for x in self._result if x['type'] != "d"]

        # get total size, directory and file counts
        lsum = sum([x['size'] for x in res if x['type'] == 'f'])
        dcount = len([x for x in res if x['type'] == 'd'])
        fcount = len(res) - dcount

        # print total size, file count if > 0, directory count if > 0
        has = len(self._result) > 0
        newline = "\n" if has else ""
        files = f"{fcount} file{'s' if fcount != 1 else ''}" if fcount > 0 else ""
        dirs = f"{dcount} director{'ies' if dcount != 1 else 'y'}" if dcount > 0 else ""
        return f"{newline} {makeHuman(lsum, len(self._result))}{' in ' if has else ''}{files}{' and ' if dcount > 0 and fcount > 0 else ''}{dirs}\n"


class JSONResponseParser(ResponseParser):
    pass
