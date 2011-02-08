
# Beaker
#
# Copyright (C) 2010 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import sys
import os
import logging
import turbogears.config
from turbogears.database import session
import unittest
import xmlrpclib
from nose.plugins.skip import SkipTest
try:
    import krbV
except ImportError:
    krbV = None
from bkr.server.test import data_setup
from bkr.server.test.selenium import SeleniumTestCase, XmlRpcTestCase

log = logging.getLogger(__name__)

class LoginTest(SeleniumTestCase):

    password = u'password'

    def setUp(self):
        self.user = data_setup.create_user(password=self.password)
        session.flush()
        self.selenium = self.get_selenium()
        self.selenium.start()

    def tearDown(self):
        self.selenium.stop()

    # https://bugzilla.redhat.com/show_bug.cgi?id=660527
    def test_referer_redirect(self):
        system = data_setup.create_system()
        session.flush()

        # Go to the system page
        sel = self.selenium
        sel.open('')
        sel.type('simplesearch', system.fqdn)
        sel.submit('systemsearch_simple')
        sel.wait_for_page_to_load('3000')
        sel.click('link=%s' % system.fqdn)
        sel.wait_for_page_to_load('3000')
        self.assertEquals(sel.get_title(), system.fqdn)

        # Click log in, and fill in details
        sel.click('link=Login')
        sel.wait_for_page_to_load('3000')
        sel.type('user_name', self.user.user_name)
        sel.type('password', self.password)
        sel.click('login')
        sel.wait_for_page_to_load('3000')

        # We should be back at the system page
        self.assertEquals(sel.get_title(), system.fqdn)

    # https://bugzilla.redhat.com/show_bug.cgi?id=663277
    def test_NestedVariablesFilter_redirect(self):
        sel = self.selenium
        # Open jobs/mine (which requires login) with some funky params
        sel.open('jobs/mine?'
                'jobsearch-0.table=Status&'
                'jobsearch-0.operation=is+not&'
                'jobsearch-0.value=Completed&'
                'jobsearch-1.table=Status&'
                'jobsearch-1.operation=is+not&'
                'jobsearch-1.value=Cancelled',
                ignoreResponseCode=True)
        # Fill in the login form
        sel.type('user_name', self.user.user_name)
        sel.type('password', self.password)
        sel.click('login')
        sel.wait_for_page_to_load('3000')
        # Did it work?
        self.assertEquals(sel.get_title(), 'My Jobs')

class XmlRpcLoginTest(XmlRpcTestCase):

    def test_krb_login(self):
        if not krbV:
            raise SkipTest('krbV module not found')
        server_princ_name = turbogears.config.get(
                'identity.krb_auth_principal', None)
        if not server_princ_name: # XXX FIXME dead test
            raise SkipTest('server not configured for krbV')

        # build krb request
        ctx = krbV.default_context()
        try:
            ccache = ctx.default_ccache()
            client_princ = ccache.principal()
        except krbV.Krb5Error:
            raise SkipTest('client ticket not found, run kinit first')
        server_princ = krbV.Principal(name=server_princ_name, context=ctx)
        ac = krbV.AuthContext(context=ctx)
        ac.flags = krbV.KRB5_AUTH_CONTEXT_DO_SEQUENCE | krbV.KRB5_AUTH_CONTEXT_DO_TIME
        ac.rcache = ctx.default_rcache()
        ac, req = ctx.mk_req(server=sprinc, client=cprinc, auth_context=ac,
                ccache=ccache, options=krbV.AP_OPTS_MUTUAL_REQUIRED)
        encoded_req = base64.encodestring(req)

        # attempt to log in
        server = self.get_server()
        server.auth.login_krbv(encoded_req)

    def test_password_login(self):
        user = data_setup.create_user(password=u'lulz')
        session.flush()
        server = self.get_server()
        server.auth.login_password(user.user_name, u'lulz')
        who_am_i = server.auth.who_am_i()
        self.assertEquals(who_am_i['username'], user.user_name)

    def test_password_proxy_login(self):
        group = data_setup.create_group(permissions=[u'proxy_auth'])
        user = data_setup.create_user(password=u'lulz')
        proxied_user = data_setup.create_user(password=u'not_used')
        data_setup.add_user_to_group(user, group)
        session.flush()
        server = self.get_server()
        server.auth.login_password(user.user_name, u'lulz', proxied_user.user_name)
        who_am_i = server.auth.who_am_i()
        self.assertEquals(who_am_i['username'], proxied_user.user_name)
        self.assertEquals(who_am_i['proxied_by_username'], user.user_name)

    # https://bugzilla.redhat.com/show_bug.cgi?id=660529
    def test_login_required_message(self):
        server = self.get_server()
        try:
            server.auth.who_am_i()
            self.fail('should raise')
        except xmlrpclib.Fault, e:
            self.assertEquals(e.faultString,
                    'turbogears.identity.exceptions.IdentityFailure: '
                    'Please log in first')
