""" Compact OwnCloud/NextCloud WebDAV client generator classes
    Author: hevp
"""

import re
from lxml import etree
from common import *

class GeneratorFactory():
    @staticmethod
    def getGenerator(data, options):
        return XMLGenerator(options)


class Generator():
    def __init__(self, data):
        self.data = data

    def getContentType(self):
        return 'text/plain'


class XMLGenerator(Generator):
    def getContentType(self):
        return 'application/xml'

    def _getXMLTag(self, tag, nsmap):
        if ':' in tag:
            tags = tag.split(':')
            tag = "{%s}%s" % (nsmap[tags[0]], tags[1])
        return tag

    def generate(self, data, element=None):
        NSMAP = {"d": "DAV:", "oc": "http://owncloud.org/ns", "nc": "http://nextcloud.org/ns"}

        try:
            # create the element itself
            xml = etree.Element(self._getXMLTag(data["root"], NSMAP), nsmap=NSMAP) if element is None else element

            # create any children recursively
            for k, v in (data["elements"].items() if element is None else data.items()):
                sub = etree.SubElement(xml, self._getXMLTag(k, NSMAP), nsmap=NSMAP)
                if type(v) is dict:
                    self.generate(v, sub)
                elif type(v) is list:
                    for l in v:
                        lk = getValueByTagReference(l.keys()[0], self.data)
                        lv = getValueByTagReference(l.values()[0], self.data)
                        prop = etree.SubElement(sub, self._getXMLTag(lk, NSMAP), nsmap=NSMAP)
                        prop.text = getValueByTagReference(lv, self.data)
                else:
                    sub.text = getValueByTagReference(v, self.data)
        except Exception as e:
            error("XML generation failed: %s " % e, 1)

        return etree.tostring(xml).decode('utf-8')
