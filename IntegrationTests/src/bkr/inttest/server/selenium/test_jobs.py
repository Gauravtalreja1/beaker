# Beaker
#
# Copyright (C) 2010 dcallagh@redhat.com
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

import unittest
import logging
import time
import re
import tempfile
import pkg_resources
from turbogears.database import session
from sqlalchemy import and_

from bkr.inttest.server.selenium import SeleniumTestCase
from bkr.inttest import data_setup
from bkr.server.model import RetentionTag, Product, Distro, Job

class TestViewJob(SeleniumTestCase):

    def setUp(self):
        self.selenium = self.get_selenium()
        self.selenium.start()

    def tearDown(self):
        self.selenium.stop()

    def test_cc_list(self):
        user = data_setup.create_user(password=u'password')
        job = data_setup.create_job(owner=user,
                cc=[u'laika@mir.su', u'tereshkova@kosmonavt.su'])
        session.flush()
        sel = self.selenium
        self.login(user=user.user_name, password='password')
        sel.open('')
        sel.click('link=My Jobs')
        sel.wait_for_page_to_load('30000')
        sel.click('link=%s' % job.t_id)
        sel.wait_for_page_to_load('30000')
        self.assert_(sel.get_title().startswith('Job %s' % job.t_id))
        self.assertEqual(
            # value of cell beside "CC" cell
            sel.get_text('//table[@class="show"]//td'
                '[preceding-sibling::td[1]/b/text() = "CC"]'),
            'laika@mir.su; tereshkova@kosmonavt.su')

    def test_edit_job_whiteboard(self):
        user = data_setup.create_user(password=u'asdf')
        job = data_setup.create_job(owner=user)
        session.flush()
        self.login(user=user.user_name, password='asdf')
        sel = self.selenium
        sel.open('jobs/%s' % job.id)
        sel.wait_for_page_to_load('30000')
        self.assert_(sel.is_editable('name=whiteboard'))
        new_whiteboard = 'new whiteboard value %s' % int(time.time())
        sel.type('name=whiteboard', new_whiteboard)
        sel.click('//form[@id="job_whiteboard_form"]//button[@type="submit"]')
        self.wait_for_condition(lambda: sel.is_element_present(
                '//form[@id="job_whiteboard_form"]//div[@class="msg success"]'))
        sel.open('jobs/%s' % job.id)
        self.assertEqual(new_whiteboard, sel.get_value('name=whiteboard'))

    def test_datetimes_are_localised(self):
        job = data_setup.create_completed_job()
        session.flush()
        sel = self.selenium
        sel.open('jobs/%s' % job.id)
        sel.wait_for_page_to_load('30000')
        self.check_datetime_localised(
                sel.get_text('//table[@class="show"]//td'
                '[preceding-sibling::td[1]/b/text() = "Queued"]'))
        self.check_datetime_localised(
                sel.get_text('//table[@class="show"]//td'
                '[preceding-sibling::td[1]/b/text() = "Started"]'))
        self.check_datetime_localised(
                sel.get_text('//table[@class="show"]//td'
                '[preceding-sibling::td[1]/b/text() = "Finished"]'))

    def test_invalid_datetimes_arent_localised(self):
        job = data_setup.create_job()
        session.flush()
        sel = self.selenium
        sel.open('jobs/%s' % job.id)
        sel.wait_for_page_to_load('30000')
        self.assertEquals(
                sel.get_text('//table[@class="show"]//td'
                '[preceding-sibling::td[1]/b/text() = "Finished"]'),
                '')

    # https://bugzilla.redhat.com/show_bug.cgi?id=706435
    def test_task_result_datetimes_are_localised(self):
        job = data_setup.create_completed_job()
        session.flush()
        sel = self.selenium
        sel.open('jobs/%s' % job.id)
        sel.wait_for_page_to_load('30000')
        recipe_id = job.recipesets[0].recipes[0].id
        sel.click('all_recipe_%d' % recipe_id)
        self.wait_for_condition(lambda: sel.is_element_present(
                '//div[@id="task_items_%d"]//table[@class="list"]' % recipe_id))
        recipe_task_start, recipe_task_finish, _ = \
                sel.get_text('//div[@id="task_items_%d"]//table[@class="list"]'
                    '/tbody/tr[2]/td[3]' % recipe_id).splitlines()
        self.check_datetime_localised(recipe_task_start.strip())
        self.check_datetime_localised(recipe_task_finish.strip())
        self.check_datetime_localised(
                sel.get_text('//div[@id="task_items_%d"]//table[@class="list"]'
                    '/tbody/tr[3]/td[3]' % recipe_id))

    def check_datetime_localised(self, dt):
        self.assert_(re.match(r'\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d [-+]\d\d:\d\d$', dt),
                '%r does not look like a localised datetime' % dt)

class NewJobTest(SeleniumTestCase):

    def setUp(self):
        if not Distro.by_name(u'BlueShoeLinux5-5'):
            data_setup.create_distro(name=u'BlueShoeLinux5-5')
        data_setup.create_task(name=u'/distribution/install')
        data_setup.create_product(product_name=u'the_product')
        session.flush()
        self.selenium = self.get_selenium()
        self.selenium.start()

    def tearDown(self):
        self.selenium.stop()

    def test_warns_about_xsd_validation_errors(self):
        self.login()
        sel = self.selenium
        sel.open('')
        sel.click('link=New Job')
        sel.wait_for_page_to_load('30000')
        xml_file = tempfile.NamedTemporaryFile()
        xml_file.write('''
            <job>
                <whiteboard>job with invalid hostRequires</whiteboard>
                <recipeSet>
                    <recipe>
                        <distroRequires>
                            <distro_name op="=" value="BlueShoeLinux5-5" />
                        </distroRequires>
                        <hostRequires/>
                        <task name="/distribution/install" role="STANDALONE">
                            <params/>
                        </task>
                        <brokenElement/>
                    </recipe>
                </recipeSet>
            </job>
            ''')
        xml_file.flush()
        sel.type('jobs_filexml', xml_file.name)
        sel.click('//input[@value="Submit Data"]')
        sel.wait_for_page_to_load('30000')
        sel.click('//input[@value="Queue"]')
        sel.wait_for_page_to_load('30000')
        self.assertEqual(sel.get_text('css=.flash'),
                'Job failed schema validation. Please confirm that you want to submit it.')
        self.assert_(int(sel.get_xpath_count('//ul[@class="xsd-error-list"]/li')) > 0)
        sel.click('//input[@value="Queue despite validation errors"]')
        sel.wait_for_page_to_load('30000')
        self.assertEqual(sel.get_title(), 'My Jobs')
        self.assert_(sel.get_text('css=.flash').startswith('Success!'))

    def test_refuses_to_accept_unparseable_xml(self):
        self.login()
        sel = self.selenium
        sel.open('')
        sel.click('link=New Job')
        sel.wait_for_page_to_load('30000')
        xml_file = tempfile.NamedTemporaryFile()
        xml_file.write('''
            <job>
                <whiteboard>job with unterminated whiteboard
            </job>
            ''')
        xml_file.flush()
        sel.type('jobs_filexml', xml_file.name)
        sel.click('//input[@value="Submit Data"]')
        sel.wait_for_page_to_load('30000')
        sel.click('//input[@value="Queue"]')
        sel.wait_for_page_to_load('30000')
        self.assert_('Failed to import job' in sel.get_text('css=.flash'))

    def test_valid_job_xml_doesnt_trigger_xsd_warning(self):
        self.login()
        sel = self.selenium
        sel.open('')
        sel.click('link=New Job')
        sel.wait_for_page_to_load('30000')
        sel.type('jobs_filexml', pkg_resources.resource_filename(
                'bkr.inttest', 'complete-job.xml'))
        sel.click('//input[@value="Submit Data"]')
        sel.wait_for_page_to_load('30000')
        sel.click('//input[@value="Queue"]')
        sel.wait_for_page_to_load('30000')
        self.assertEqual(sel.get_title(), 'My Jobs')
        self.assert_(sel.get_text('css=.flash').startswith('Success!'))

    # https://bugzilla.redhat.com/show_bug.cgi?id=661652
    def test_job_with_excluded_task(self):
        distro = data_setup.create_distro(arch=u'ia64')
        excluded_task = data_setup.create_task(exclude_arch=[u'ia64'])
        session.flush()
        self.login()
        sel = self.selenium
        sel.open('')
        sel.click('link=New Job')
        sel.wait_for_page_to_load('30000')
        xml_file = tempfile.NamedTemporaryFile()
        xml_file.write('''
            <job>
                <whiteboard>job with excluded task</whiteboard>
                <recipeSet>
                    <recipe>
                        <distroRequires>
                            <distro_name op="=" value="%s" />
                            <distro_arch op="=" value="ia64" />
                        </distroRequires>
                        <hostRequires/>
                        <task name="/distribution/install" role="STANDALONE">
                            <params/>
                        </task>
                        <task name="%s" role="STANDALONE">
                            <params/>
                        </task>
                    </recipe>
                </recipeSet>
            </job>
            ''' % (distro.name, excluded_task.name))
        xml_file.flush()
        sel.type('jobs_filexml', xml_file.name)
        sel.click('//input[@value="Submit Data"]')
        sel.wait_for_page_to_load('30000')
        sel.click('//input[@value="Queue"]')
        sel.wait_for_page_to_load('30000')
        flash = sel.get_text('css=.flash')
        self.assert_(flash.startswith('Success!'), flash)
        self.assertEqual(sel.get_title(), 'My Jobs')

    # https://bugzilla.redhat.com/show_bug.cgi?id=689344
    def test_partition_without_fs_doesnt_trigger_validation_warning(self):
        self.login()
        sel = self.selenium
        sel.open('')
        sel.click('link=New Job')
        sel.wait_for_page_to_load('30000')
        xml_file = tempfile.NamedTemporaryFile()
        xml_file.write('''
            <job>
                <whiteboard>job with partition without fs</whiteboard>
                <recipeSet>
                    <recipe>
                        <distroRequires>
                            <distro_name op="=" value="BlueShoeLinux5-5" />
                        </distroRequires>
                        <hostRequires/>
                        <partitions>
                            <partition name="/" size="4" type="part"/>
                        </partitions>
                        <task name="/distribution/install" role="STANDALONE"/>
                    </recipe>
                </recipeSet>
            </job>
            ''')
        xml_file.flush()
        sel.type('jobs_filexml', xml_file.name)
        sel.click('//input[@value="Submit Data"]')
        sel.wait_for_page_to_load('30000')
        sel.click('//input[@value="Queue"]')
        sel.wait_for_page_to_load('30000')
        flash = sel.get_text('css=.flash')
        self.assert_(flash.startswith('Success!'), flash)
        self.assertEqual(sel.get_title(), 'My Jobs')

    # https://bugzilla.redhat.com/show_bug.cgi?id=730983
    def test_duplicate_notify_cc_addresses_are_merged(self):
        user = data_setup.create_user(password=u'hornet')
        session.flush()
        self.login(user.user_name, u'hornet')
        sel = self.selenium
        sel.open('')
        sel.click('link=New Job')
        sel.wait_for_page_to_load('30000')
        xml_file = tempfile.NamedTemporaryFile()
        xml_file.write('''
            <job>
                <whiteboard>job with duplicate notify cc addresses</whiteboard>
                <notify>
                    <cc>person@example.invalid</cc>
                    <cc>person@example.invalid</cc>
                </notify>
                <recipeSet>
                    <recipe>
                        <distroRequires>
                            <distro_name op="=" value="BlueShoeLinux5-5" />
                        </distroRequires>
                        <hostRequires/>
                        <task name="/distribution/install" role="STANDALONE"/>
                    </recipe>
                </recipeSet>
            </job>
            ''')
        xml_file.flush()
        sel.type('jobs_filexml', xml_file.name)
        sel.click('//input[@value="Submit Data"]')
        sel.wait_for_page_to_load('30000')
        sel.click('//input[@value="Queue"]')
        sel.wait_for_page_to_load('30000')
        flash = sel.get_text('css=.flash')
        self.assert_(flash.startswith('Success!'), flash)
        self.assertEqual(sel.get_title(), 'My Jobs')
        job = Job.query.filter(Job.owner == user).order_by(Job.id.desc()).first()
        self.assertEqual(job.cc, ['person@example.invalid'])

    # https://bugzilla.redhat.com/show_bug.cgi?id=741170
    # You will need a patched python-xmltramp for this test to pass.
    # Look for python-xmltramp-2.17-8.eso.1 or higher.
    def test_doesnt_barf_on_xmlns(self):
        self.login()
        sel = self.selenium
        sel.open('')
        sel.click('link=New Job')
        sel.wait_for_page_to_load('30000')
        xml_file = tempfile.NamedTemporaryFile()
        xml_file.write('''
            <job>
                <whiteboard>job with namespace prefix declaration</whiteboard>
                <recipeSet>
                    <recipe>
                        <distroRequires xmlns:str="http://exslt.org/strings">
                            <distro_name op="=" value="BlueShoeLinux5-5" />
                        </distroRequires>
                        <hostRequires/>
                        <task name="/distribution/install" role="STANDALONE"/>
                    </recipe>
                </recipeSet>
            </job>
            ''')
        xml_file.flush()
        sel.type('jobs_filexml', xml_file.name)
        sel.click('//input[@value="Submit Data"]')
        sel.wait_for_page_to_load('30000')
        sel.click('//input[@value="Queue"]')
        sel.wait_for_page_to_load('30000')
        flash = sel.get_text('css=.flash')
        self.assert_(flash.startswith('Success!'), flash)
        self.assertEqual(sel.get_title(), 'My Jobs')

class JobAttributeChange(SeleniumTestCase):

    def setUp(self):
        self.password = 'password'
        self.the_group = data_setup.create_group()

        self.user_one = data_setup.create_user(password=self.password)
        self.user_two = data_setup.create_user(password=self.password)
        self.user_three = data_setup.create_user(password=self.password)

        self.user_one.groups.append(self.the_group)
        self.user_two.groups.append(self.the_group)
        self.the_job  = data_setup.create_job(owner=self.user_one)
        session.flush()
        self.selenium = self.get_selenium()
        self.selenium.start()

    def tearDown(self):
        self.selenium.stop()

    def test_change_product(self):
        p1 = Product(u'first_product')
        p2 = Product(u'second_product')

        self.the_job.product = p1
        self.the_job.retention_tag = RetentionTag.query.filter(
            RetentionTag.needs_product==True).first()
        session.flush()

        #With Owner
        sel = self.selenium
        self.login(user=self.user_one.user_name, password=self.password)
        sel.open('jobs/%s' % self.the_job.id)
        sel.wait_for_page_to_load('30000')
        sel.select("job_product", "label=%s" % p2.name )
        self.wait_and_try(lambda: self.assert_(sel.is_text_present("Product has been updated")), wait_time=10)

        #With Group member
        self.logout()
        self.login(user=self.user_two.user_name, password=self.password)
        sel.open('jobs/%s' % self.the_job.id)
        sel.wait_for_page_to_load('30000')
        sel.select("job_product", "label=%s" % p1.name )
        self.wait_and_try(lambda: self.assert_(sel.is_text_present("Product has been updated")), wait_time=10)

        # With Non group member
        self.logout()
        self.login(user=self.user_three.user_name, password=self.password)
        sel.open('jobs/%s' % self.the_job.id)
        sel.wait_for_page_to_load('30000')
        disabled_product = sel.get_text("//select[@id='job_product' and @disabled]")
        self.assert_(disabled_product is not None)


    def test_change_retention_tag(self):
        sel = self.selenium

        #With Owner
        self.login(user=self.user_one.user_name, password=self.password)
        sel.open('jobs/%s' % self.the_job.id)
        sel.wait_for_page_to_load('30000')
        current_tag = sel.get_text("//select[@id='job_retentiontag']/option[@selected='']")
        new_tag = RetentionTag.query.filter(and_(RetentionTag.tag != current_tag,
            RetentionTag.needs_product==False)).first()
        sel.select("job_retentiontag", "label=%s" % new_tag.tag)
        self.wait_and_try(lambda: self.assert_(sel.is_text_present("Tag has been updated")), wait_time=10)

        #With Group member
        self.logout()
        self.login(user=self.user_two.user_name, password=self.password)
        sel.open('jobs/%s' % self.the_job.id)
        sel.wait_for_page_to_load('30000')
        current_tag = sel.get_text("//select[@id='job_retentiontag']/option[@selected='']")
        new_tag = RetentionTag.query.filter(and_(RetentionTag.tag != current_tag,
            RetentionTag.needs_product==False)).first()
        sel.select("job_retentiontag", "label=%s" % new_tag.tag)
        self.wait_and_try(lambda: self.assert_(sel.is_text_present("Tag has been updated")), wait_time=10)

        #With Non Group member
        self.logout()
        self.login(user=self.user_three.user_name, password=self.password)
        sel.open('jobs/%s' % self.the_job.id)
        sel.wait_for_page_to_load('30000')
        disabled_tag = sel.get_text("//select[@id='job_retentiontag' and @disabled]")
        self.assert_(disabled_tag is not None)
 

class CloneJobTest(SeleniumTestCase):

    def setUp(self):
        self.selenium = self.get_selenium()
        self.selenium.start()

    def tearDown(self):
        self.selenium.stop()

    def test_cloning_recipeset_from_job_with_product(self):
        job = data_setup.create_job()
        job.retention_tag = RetentionTag.list_by_requires_product()[0]
        job.product = Product(u'product_name')
        session.flush()
        self.login()
        sel =  self.selenium
        sel.open('jobs/clone?job_id=%s' % job.id)
        sel.wait_for_page_to_load('30000')
        cloned_from_job = sel.get_text('//textarea[@id="job_textxml"]')
        sel.open('jobs/clone?recipeset_id=%s' % job.recipesets[0].id)
        sel.wait_for_page_to_load('30000')
        cloned_from_rs = sel.get_text('//textarea[@id="job_textxml"]')
        self.assertEqual(cloned_from_job,cloned_from_rs)

    def test_cloning_recipeset(self):
        job = data_setup.create_job()
        session.flush()
        self.login()
        sel = self.selenium
        sel.open('jobs/clone?job_id=%s' % job.id)
        sel.wait_for_page_to_load('30000')
        cloned_from_job = sel.get_text('//textarea[@id="job_textxml"]')
        sel.open('jobs/clone?recipeset_id=%s' % job.recipesets[0].id)
        sel.wait_for_page_to_load('30000')
        cloned_from_rs = sel.get_text('//textarea[@id="job_textxml"]')
        self.assertEqual(cloned_from_job, cloned_from_rs)
