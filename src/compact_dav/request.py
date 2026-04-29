import cchardet
import re
import requests
import simplejson

from lxml import etree
from .common import error, verbose, debug, warning
from .config import Config

class DAVRequest():
    """ WebDAV request class for WebDAV-enabled servers """

    SUCCESS = [200, 201, 204, 207]

    def __init__(self):
        self.result = None
        self.request = None
        self.response = None
        self.download = {}
        self.success = False
        self.session = requests.Session()

    def run(self, method, path, expectedStatus=SUCCESS, **kwargs):
        verbose(f"Request data: {data[:1000] if isinstance(data := kwargs.get('data', None), str) else type(data)}")

        if Config['head']:
            method = "HEAD"

        # construct url
        url = f"{Config['credentials']['hostname']}{Config['credentials']['endpoint']}"
        if not Config['no-path']:
            url += path

        # construct request
        req = requests.Request(method, url, **kwargs)

        self.request = req.prepare()
        self.success = False

        verbose(f"Request headers: {self.request.headers}")

        # exit if dry-run
        if Config['dry-run']:
            warning(f"dry-run: {method.upper()} {req.url}")
            return False

        # some debug messages
        verbose(f"Options: {Config}")
        debug(f"{method.upper()} {self.request.url}")

        # do request
        try:
            self.response = self.session.send(self.request, verify=not Config['no-verify'], timeout=Config['timeout'])
        except requests.exceptions.ReadTimeout:
            error("request time out after 30 seconds", 2)
        except Exception as e:
            error(e, 2)

        # determine the encoding of the response text
        if self.response.encoding is None:
            self.response.encoding = cchardet.detect(self.response.content)['encoding']

        # print headers, exit if only head request
        if Config['headers'] or Config['head']:
            debug(f"Response headers: {self.response.headers}", True)
            if Config['head']:
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
                error(f"invalid response header disposition value: {self.response.headers['Content-Disposition']}", 1)
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
        if 'Content-Type' in self.response.headers and not Config['no-parse']:
            info = self.response.headers['Content-Type'].split(';')
            if info[0] in ['application/xml', 'text/xml']:
                try:
                    self.result = etree.fromstring(self.result.encode('utf-8'))
                except Exception as e:
                    error(f"could not decode XML data: {e}")
            elif info[0] in ['application/json', 'text/json']:
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

        suffix = f": {message}" if message > "" else ""
        return error(f"{self.response.reason} ({self.response.status_code}){suffix}")


class DAVAuthRequest(DAVRequest):
    def run(self, method, path, expectedStatus=DAVRequest.SUCCESS, **kwargs):
        return DAVRequest.run(self, method, path, expectedStatus=expectedStatus,
                              auth=(Config["credentials"]["user"], Config["credentials"]["token"]) if 'Authorization' not in kwargs.get('headers', {}) else None,
                              **kwargs)
