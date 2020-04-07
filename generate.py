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
    def __init__(self, options):
        self.options = options

    def _replaceValueTags(self, v):
        for m in re.findall('@([0-9]+)|@{([\w\.\-]+)}', v):
            rv = m[1] if m[1] > '' else m[0]
            rs = "@%s" % (("{%s}" % m[1]) if m[1] > '' else m[0])
            ov = getFromDict(self.options, rv.split('.'))
            v = v.replace(rs, ov) if ov else v
        return v

class XMLGenerator(Generator):
    def _getXMLTag(self, tag, nsmap):
        if ':' in tag:
            tags = tag.split(':')
            tag = "{%s}%s" % (nsmap[tags[0]], tags[1])
        return tag

    def generate(self, data, element=None):
        NSMAP = {"d": "DAV:", "oc": "http://owncloud.org/ns", "nc": "http://nextcloud.org/ns"}

        #try:
        # create the element itself
        xml = etree.Element(self._getXMLTag(data["root"], NSMAP), nsmap=NSMAP) if element is None else element

        # create any children recursively
        for k, v in (data["elements"].items() if element is None else data.items()):
            sub = etree.SubElement(xml, self._getXMLTag(k, NSMAP), nsmap=NSMAP)
            if type(v) is dict:
                self.generate(v, sub)
            elif type(v) is list:
                for l in v:
                    lk = getArgumentByTagReference(list(l.keys())[0])
                    lv = getArgumentByTagReference(list(l.values())[0])
                    prop = etree.SubElement(sub, self._getXMLTag(lk, NSMAP), nsmap=NSMAP)
                    prop.text = self._replaceValueTags(lv)
            else:
                sub.text = self._replaceValueTags(v)
        # except Exception as e:
        #    error("XML generation failed: %s " % e, 1)

        return etree.tostring(xml).decode('utf-8')
