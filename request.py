import cchardet
import re
import requests
import simplejson

from lxml import etree
from common import error, verbose, debug, warning

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

    def run(self, method, path, headers={}, params={}, data="", expectedStatus=SUCCESS, auth=None):
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
            debug(f"Response headers: {self.response.headers}", True)
            if self.options['head']:
                return False

        debug(f"Response: {self.response.status_code} {self.response.reason}")
        verbose(f"Response: {self.response.text}")

        # init result
        self.result = self.response.text

        # if failed exit
        if self.response.status_code not in expectedStatus:
            return self.result  # self._requestfail() if not quiet else False

        # check if downloading file
        if 'Content-Disposition' in self.response.headers:
            # extract filename
            m = re.match(r'attachment;.+filename="([^"]+)"', self.response.headers['Content-Disposition'])
            if not m:
                error("invalid response header disposition value: %s" % self.response.headers['Content-Disposition'], 1)
            else:
                self.download['filename'] = m.group(1)
            # extract checksum if available
            if 'OC-Checksum' in self.response.headers:
                m = re.match(r'^([^:]+):([0-9a-f]+)$', self.response.headers['OC-Checksum'])
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
                    error(f"could not decode XML data: {e}")
            elif info[0] == 'application/json':
                try:
                    self.result = simplejson.loads(self.result)
                except Exception as e:
                    error(f"could not decode JSON data: {e}")

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
