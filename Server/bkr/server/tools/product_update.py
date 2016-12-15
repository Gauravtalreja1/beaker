
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# pkg_resources.requires() does not work if multiple versions are installed in 
# parallel. This semi-supported hack using __requires__ is the workaround.
# http://bugs.python.org/setuptools/issue139
# (Fedora/EPEL has python-cherrypy2 = 2.3 and python-cherrypy = 3)
__requires__ = ['CherryPy < 3.0']

import sys
import cgi
from bkr.common import __version__
from bkr.log import log_to_stream
from bkr.server.model import Product
from bkr.server.util import load_config_or_exit
import lxml.etree
import requests
from optparse import OptionParser
from turbogears.database import session

__description__ = 'Update CPE identifiers for products in Beaker'

def get_parser():
    parser = OptionParser(description=__description__, version=__version__)
    parser.add_option('-c', '--config-file', metavar='FILE', dest='configfile',
            help='Load Beaker server configuration from FILE')
    parser.add_option('-f', '--product-file', metavar='FILE', dest='productfile',
            help='Load product XML data from FILE')
    parser.add_option('--product-url', metavar='URL', dest='producturl',
            help='Load product XML or JSON data from URL')
    return parser

def update_products(xml_file):
    xml = lxml.etree.parse(xml_file)
    with session.begin():
        for element in xml.xpath('//cpe'):
            # lxml returns text as str if it's ASCII, else unicode...
            if isinstance(element.text, str):
                cpe = element.text.decode('ascii')
            else:
                cpe = element.text
            if cpe:
                Product.lazy_create(name=cpe)

def main():
    parser = get_parser()
    opts, args = parser.parse_args()

    if not opts.productfile and not opts.producturl:
        parser.error('Specify product data to load using --product-file or --product-url')

    load_config_or_exit(opts.configfile)
    log_to_stream(sys.stderr)

    if opts.productfile:
        xml_file = open(opts.productfile, 'rb')
    elif opts.producturl:
        response = requests.get(opts.producturl, stream=True)
        response.raise_for_status()
        mimetype, options = cgi.parse_header(response.headers['Content-Type'])
        if mimetype not in ['text/xml', 'application/xml']:
            raise ValueError('Resource at %s is not XML' % opts.producturl)
        xml_file = response.raw
    update_products(xml_file)

if __name__ == '__main__':
    main()
