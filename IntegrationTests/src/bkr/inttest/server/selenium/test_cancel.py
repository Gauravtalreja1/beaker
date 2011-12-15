#!/usr/bin/python

from bkr.inttest.server.selenium import SeleniumTestCase
from bkr.inttest import data_setup
import unittest, time, re, os
from turbogears.database import session

class Cancel(SeleniumTestCase):

    def setUp(self):
        self.password = 'password'
        self.user = data_setup.create_user(password=self.password)
        self.job = data_setup.create_job(owner=self.user)
        session.flush()
        self.selenium = self.get_selenium()
        self.selenium.start()

    def test_cancel_recipeset(self):
        sel = self.selenium
        self.login(user=self.user, password=self.password)
        sel.open('jobs/%s' % self.job.id)
        sel.wait_for_page_to_load("30000")
        #sel.click("(//a[text()='Cancel'])[last()]")
        sel.click("//div[@id='fedora-content']/div[3]/div[1]/div/table/tbody/tr/td[7]/div/a[2]")
        sel.wait_for_page_to_load("30000")
        sel.click("//input[@value='Yes']")
        sel.wait_for_page_to_load("30000")
        
        self.assertTrue(sel.is_text_present("Successfully cancelled recipeset %s" % self.job.recipesets[0].id))

    def tearDown(self):
        self.selenium.stop()
