
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import datetime
import logging
import re
import requests
from turbogears.database import session

from bkr.server.model import TaskStatus, TaskResult, RecipeTaskResult, Task
from bkr.inttest.server.selenium import WebDriverTestCase
from bkr.inttest.server.webdriver_utils import login, is_text_present
from bkr.inttest import data_setup, get_server_base, DatabaseTestCase
from bkr.inttest.assertions import assert_sorted
from bkr.inttest.server.requests_utils import post_json, patch_json, \
        put_json, login as requests_login
from bkr.inttest.assertions import assert_datetime_within


class TestRecipesDataGrid(WebDriverTestCase):

    log = logging.getLogger(__name__ + '.TestRecipesIndex')

    @classmethod
    def setUpClass(cls):
        # create a bunch of jobs
        with session.begin():
            cls.user = user = data_setup.create_user(password='password')
            arches = [u'i386', u'x86_64', u'ia64']
            distros = [data_setup.create_distro(name=name) for name in
                    [u'DAN5-Server-U5', u'DAN5-Client-U5', u'DAN6-U1', u'DAN6-RC3']]
            for arch in arches:
                for distro in distros:
                    distro_tree = data_setup.create_distro_tree(distro=distro, arch=arch)
                    data_setup.create_job(owner=user, distro_tree=distro_tree)
                    data_setup.create_completed_job(owner=user, distro_tree=distro_tree)

    def setUp(self):
        self.browser = self.get_browser()
        login(self.browser, user=self.user.user_name, password='password')

    # see https://bugzilla.redhat.com/show_bug.cgi?id=629147
    def check_column_sort(self, column, sort_key=None):
        b = self.browser
        b.get(get_server_base() + 'recipes/mine')
        b.find_element_by_xpath('//table[@id="widget"]/thead//th[%d]//a[@href]' % column).click()
        row_count = len(b.find_elements_by_xpath('//table[@id="widget"]/tbody/tr/td[%d]' % column))
        self.assertEquals(row_count, 24)
        cell_values = [b.find_element_by_xpath('//table[@id="widget"]/tbody/tr[%d]/td[%d]' % (row, column)).text
                       for row in range(1, row_count + 1)]
        assert_sorted(cell_values, key=sort_key)

    def test_can_sort_by_whiteboard(self):
        self.check_column_sort(2)

    def test_can_sort_by_arch(self):
        self.check_column_sort(3)

    def test_can_sort_by_system(self):
        self.check_column_sort(4)

    def test_can_sort_by_status(self):
        order = ['New', 'Processed', 'Queued', 'Scheduled', 'Waiting',
                'Running', 'Completed', 'Cancelled', 'Aborted']
        self.check_column_sort(7, sort_key=lambda status: order.index(status))

    def test_can_sort_by_result(self):
        self.check_column_sort(8)

    # this version is different since the cell values will be like ['R:1', 'R:10', ...]
    def test_can_sort_by_id(self):
        column = 1
        b = self.browser
        b.get(get_server_base() + 'recipes/mine')
        b.find_element_by_xpath('//table[@id="widget"]/thead//th[%d]//a[@href]' % column).click()
        row_count = len(b.find_elements_by_xpath('//table[@id="widget"]/tbody/tr/td[%d]' % column))
        self.assertEquals(row_count, 24)
        cell_values = []
        for row in range(1, row_count + 1):
            raw_value = b.find_element_by_xpath('//table[@id="widget"]/tbody/tr[%d]/td[%d]' % (row, column)).text
            m = re.match(r'R:(\d+)$', raw_value)
            assert m.group(1)
            cell_values.append(int(m.group(1)))
        assert_sorted(cell_values)


class TestRecipeView(WebDriverTestCase):

    def setUp(self):
        with session.begin():
            self.user = user = data_setup.create_user(display_name=u'Bob Brown',
                    password='password')
            self.system_owner = data_setup.create_user()
            self.system = data_setup.create_system(owner=self.system_owner, arch=u'x86_64')
            self.distro_tree = data_setup.create_distro_tree(arch=u'x86_64')
            self.job = data_setup.create_completed_job(owner=user,
                    distro_tree=self.distro_tree, server_log=True)
            for recipe in self.job.all_recipes:
                recipe.system = self.system
        self.browser = self.get_browser()

    def go_to_recipe_view(self, recipe=None, tab=None):
        if recipe is None:
            recipe = self.job.recipesets[0].recipes[0]
        b = self.browser
        b.get(get_server_base() + 'recipes/%s' % recipe.id)
        if tab:
            b.find_element_by_xpath('//ul[contains(@class, "recipe-nav")]'
                    '//a[text()="%s"]' % tab).click()

    def test_log_url_looks_right(self):
        b = self.browser
        self.go_to_recipe_view(tab='Installation')
        tab = b.find_element_by_id('recipe-installation')
        log_link = tab.find_element_by_xpath('//span[@class="main-log"]/a')
        self.assertEquals(log_link.get_attribute('href'),
            get_server_base() + 'recipes/%s/logs/recipe_path/dummy.txt' %
                    self.job.recipesets[0].recipes[0].id)

    # https://bugzilla.redhat.com/show_bug.cgi?id=1072133
    def test_watchdog_time_remaining_display(self):
        b = self.browser
        with session.begin():
            recipe = data_setup.create_recipe()
            job = data_setup.create_job_for_recipes([recipe], owner=self.user)
            data_setup.mark_job_running(job)
            recipe.watchdog.kill_time = (datetime.datetime.utcnow() +
                    datetime.timedelta(seconds=83 * 60 + 30))
        self.go_to_recipe_view(recipe)
        duration = b.find_element_by_class_name('recipe-watchdog-time-remaining')
        self.assertRegexpMatches(duration.text, r'^Remaining watchdog time: 01:\d\d:\d\d')
        with session.begin():
            recipe.watchdog.kill_time = (datetime.datetime.utcnow() +
                    datetime.timedelta(days=2, seconds=83 * 60 + 30))
        self.go_to_recipe_view(recipe)
        duration = b.find_element_by_class_name('recipe-watchdog-time-remaining')
        self.assertRegexpMatches(duration.text, r'^Remaining watchdog time: 49:\d\d:\d\d')

    def test_task_versions_are_shown(self):
        with session.begin():
            recipe = data_setup.create_recipe()
            job = data_setup.create_job_for_recipes([recipe])
            recipetask = recipe.tasks[0]
            recipetask.version = u'1.10-23'
        b = self.browser
        self.go_to_recipe_view(recipe, tab='Tasks')
        self.assertIn('1.10-23', b.find_element_by_xpath('//div[@id="task%s"]'
                '//span[contains(@class, "task-name")]' % recipetask.id).text)

    def test_anonymous_cannot_edit_whiteboard(self):
        b = self.browser
        self.go_to_recipe_view()
        b.find_element_by_xpath('//div[@class="recipe-page-header" and '
                'not(.//button[normalize-space(string(.))="Edit"])]')

    def test_authenticated_user_can_edit_whiteboard(self):
        with session.begin():
            job = data_setup.create_job(owner=self.user)
            recipe = job.recipesets[0].recipes[0]
        b = self.browser
        login(b)
        self.go_to_recipe_view(recipe)
        b.find_element_by_xpath('.//button[contains(text(), "Edit")]').click()
        modal = b.find_element_by_class_name('modal')
        modal.find_element_by_name('whiteboard').clear()
        modal.find_element_by_name('whiteboard').send_keys('testwhiteboard')
        modal.find_element_by_xpath('.//button[text()="Save changes"]').click()
        b.find_element_by_xpath('//body[not(.//div[contains(@class, "modal")])]')
        with session.begin():
            session.refresh(recipe)
            self.assertEqual(recipe.whiteboard, 'testwhiteboard')


    def test_first_faild_task_should_expand_when_first_loading(self):
        with session.begin():
            recipe = data_setup.create_recipe(task_list=[
                Task.by_name(u'/distribution/install'),
                Task.by_name(u'/distribution/reservesys')
            ])
            job = data_setup.create_job_for_recipes([recipe])
            data_setup.mark_recipe_tasks_finished(recipe, result=TaskResult.fail)
            job.update_status()
        b = self.browser
        self.go_to_recipe_view(recipe, tab='Tasks')
        tab = b.find_element_by_id('recipe-tasks')
        # The in class is an indication that a task is expanded.
        tab.find_element_by_xpath('//div[@id="recipe-task-details-%s" and '
            'contains(@class, "in")]' % recipe.tasks[0].id)

    def test_task_without_failed_results_should_not_expand(self):
        with session.begin():
            recipe = data_setup.create_recipe(task_list=[
                Task.by_name(u'/distribution/install'),
                Task.by_name(u'/distribution/reservesys')
            ])
            job = data_setup.create_job_for_recipes([recipe])
            data_setup.mark_recipe_tasks_finished(recipe, result=TaskResult.pass_)
            job.update_status()
        b = self.browser
        self.go_to_recipe_view(recipe, tab='Tasks')
        tab = b.find_element_by_id('recipe-tasks')
        for task in recipe.tasks:
            tab.find_element_by_xpath('//div[@id="recipe-task-details-%s" and '
                    'not(contains(@class, "in"))]' % task.id)

    # https://bugzilla.redhat.com/show_bug.cgi?id=706435
    def test_task_start_time_is_localised(self):
        with session.begin():
            recipe = data_setup.create_recipe()
            data_setup.create_job_for_recipes([recipe])
            data_setup.mark_recipe_running(recipe)
        b = self.browser
        self.go_to_recipe_view(recipe, tab='Tasks')
        tab = b.find_element_by_id('recipe-tasks')
        start_time = tab.find_element_by_xpath('//div[@id="task%s"]'
                '//div[@class="task-start-time"]/time' % recipe.tasks[0].id)
        self.check_datetime_localised(start_time.get_attribute('title'))

    def check_datetime_localised(self, dt):
        self.assert_(re.match(r'\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d [-+]\d\d:\d\d$', dt),
                '%r does not look like a localised datetime' % dt)

    def test_anonymous_cannot_edit_reservation(self):
        with session.begin():
            recipe = data_setup.create_recipe(reservesys=True)
            job = data_setup.create_job_for_recipes([recipe])
            data_setup.mark_job_running(job)
        b = self.browser
        self.go_to_recipe_view(recipe, tab='Reservation')
        b.find_element_by_xpath('//div[@id="recipe-reservation" and '
                'not(.//button[normalize-space(string(.))="Edit"])]')

    def test_authenticated_user_can_request_reservation(self):
        with session.begin():
            recipe = data_setup.create_recipe()
            job = data_setup.create_job_for_recipes([recipe])
            data_setup.mark_job_running(job)
        b = self.browser
        login(b)
        self.go_to_recipe_view(recipe, tab='Reservation')
        tab = b.find_element_by_id('recipe-reservation')
        tab.find_element_by_xpath('.//button[contains(text(), "Edit")]').click()
        modal = b.find_element_by_class_name('modal')
        modal.find_element_by_xpath('.//button[text()="Yes"]').click()
        modal.find_element_by_name('duration').clear()
        modal.find_element_by_name('duration').send_keys('300')
        modal.find_element_by_xpath('.//button[text()="Save changes"]').click()
        b.find_element_by_xpath('//body[not(.//div[contains(@class, "modal")])]')
        self.assertIn('The system will be reserved for 00:05:00 at the end of the recipe',
            tab.text)
        with session.begin():
            session.expire_all()
            self.assertEqual(recipe.reservation_request.duration, 300)

    def test_authenticated_user_can_edit_reservation(self):
        with session.begin():
            recipe = data_setup.create_recipe(reservesys=True)
            job = data_setup.create_job_for_recipes([recipe])
            data_setup.mark_job_running(job)
        b = self.browser
        login(b)
        self.go_to_recipe_view(recipe, tab='Reservation')
        tab = b.find_element_by_id('recipe-reservation')
        tab.find_element_by_xpath('.//button[contains(text(), "Edit")]').click()
        modal = b.find_element_by_class_name('modal')
        modal.find_element_by_name('duration').clear()
        modal.find_element_by_name('duration').send_keys('300')
        modal.find_element_by_xpath('.//button[text()="Save changes"]').click()
        b.find_element_by_xpath('//body[not(.//div[contains(@class, "modal")])]')
        with session.begin():
            session.expire_all()
            self.assertEqual(recipe.reservation_request.duration, 300)

    def test_anonymous_cannot_extend_or_return_reservation(self):
        with session.begin():
            recipe = data_setup.create_recipe(reservesys=True)
            data_setup.create_job_for_recipes([recipe])
            data_setup.mark_recipe_complete(recipe)
        b = self.browser
        self.go_to_recipe_view(recipe, tab='Reservation')
        #No extend button
        b.find_element_by_xpath('//div[@id="recipe-reservation" and '
                'not(.//button[normalize-space(string(.))="Extend the reservation"])]')

        #No return button
        b.find_element_by_xpath('//div[@id="recipe-reservation" and '
                'not(.//button[normalize-space(string(.))="Return the reservation"])]')

    def test_authenticated_user_can_extend_reservation(self):
        with session.begin():
            recipe = data_setup.create_recipe(reservesys=True)
            job = data_setup.create_job_for_recipes([recipe])
            data_setup.mark_recipe_tasks_finished(recipe)
            job.update_status()
        b = self.browser
        login(b)
        self.go_to_recipe_view(recipe, tab='Reservation')
        tab = b.find_element_by_id('recipe-reservation')
        tab.find_element_by_xpath('.//button[contains(text(), "Extend the reservation")]')\
                .click()
        modal = b.find_element_by_class_name('modal')
        modal.find_element_by_name('kill_time').clear()
        modal.find_element_by_name('kill_time').send_keys('600')
        modal.find_element_by_xpath('.//button[text()="Save changes"]').click()
        b.find_element_by_xpath('//body[not(.//div[contains(@class, "modal")])]')
        with session.begin():
            session.expire_all()
            assert_datetime_within(recipe.watchdog.kill_time,
                    tolerance=datetime.timedelta(seconds=10),
                    reference=datetime.datetime.utcnow() + datetime.timedelta(seconds=600))

    def test_authenticated_user_can_return_reservation(self):
        with session.begin():
            recipe = data_setup.create_recipe(reservesys=True)
            job = data_setup.create_job_for_recipes([recipe])
            data_setup.mark_recipe_tasks_finished(recipe)
            job.update_status()
        b = self.browser
        login(b)
        self.go_to_recipe_view(recipe, tab='Reservation')
        tab = b.find_element_by_id('recipe-reservation')
        tab.find_element_by_xpath('.//button[contains(text(), "Return the reservation")]')\
                .click()
        modal = b.find_element_by_class_name('modal')
        modal.find_element_by_xpath('.//button[text()="OK"]').click()
        b.find_element_by_xpath('//body[not(.//div[contains(@class, "modal")])]')
        # The `Return the reservtion` button should be gone.
        tab.find_element_by_xpath('//div[not(.//button[normalize-space(string(.))='
                '"Return the reservation"])]')
        with session.begin():
            session.expire_all()
            self.assertLessEqual(recipe.status_watchdog(), 0)

    def test_opening_recipe_page_marks_it_as_reviewed(self):
        with session.begin():
            recipe = self.job.recipesets[0].recipes[0]
            self.assertEqual(recipe.get_reviewed_state(self.user), False)
        b = self.browser
        login(b, user=self.user.user_name, password='password')
        self.go_to_recipe_view(recipe)
        b.find_element_by_xpath('//h1[contains(string(.), "%s")]' % recipe.t_id)
        with session.begin():
            self.assertEqual(recipe.get_reviewed_state(self.user), True)


class RecipeHTTPTest(DatabaseTestCase):
    """
    Directly tests the HTTP interface for recipes.
    """

    def setUp(self):
        with session.begin():
            self.owner = data_setup.create_user(password='theowner')
            self.recipe = data_setup.create_recipe()
            self.recipe_with_reservation_request = data_setup.create_recipe(reservesys=True)
            self.recipe_without_reservation_request = data_setup.create_recipe()
            self.job = data_setup.create_job_for_recipes([
                    self.recipe,
                    self.recipe_with_reservation_request,
                    self.recipe_without_reservation_request],
                    owner=self.owner)

    def test_get_recipe(self):
        response = requests.get(get_server_base() +
                'recipes/%s' % self.recipe.id,
                headers={'Accept': 'application/json'})
        response.raise_for_status()
        json = response.json()
        self.assertEquals(json['t_id'], self.recipe.t_id)

    def test_410_for_deleted_job(self):
        with session.begin():
            job = data_setup.create_completed_job()
            job.soft_delete()
            recipe = job.recipesets[0].recipes[0]
        response = requests.get(get_server_base() +
                'recipes/%s' % recipe.id,
                headers={'Accept': 'application/json'})
        self.assertEqual(response.status_code, 410)
        self.assertRegexpMatches(response.text, 'Job %s is deleted' % job.id)

    def test_get_recipe_log(self):
        with session.begin():
            job = data_setup.create_completed_job(server_log=True)
            recipe = job.recipesets[0].recipes[0]
        response = requests.get(get_server_base() +
                'recipes/%s/logs/recipe_path/dummy.txt' % recipe.id,
                allow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers['Location'],
                'http://dummy-archive-server/beaker/recipe_path/dummy.txt')

    def test_404_for_nonexistent_log(self):
        with session.begin():
            job = data_setup.create_completed_job(server_log=True)
            recipe = job.recipesets[0].recipes[0]
        response = requests.get(get_server_base() +
                'recipes/%s/logs/doesnotexist.log' % recipe.id,
                allow_redirects=False)
        self.assertEqual(response.status_code, 404)
        self.assertRegexpMatches(response.text, 'Recipe log .* not found')

    def test_anonymous_cannot_update_recipe(self):
        response = patch_json(get_server_base() +
                'recipes/%s' % self.recipe.id,
                data={'whiteboard': u'testwhiteboard'})
        self.assertEquals(response.status_code, 401)

    def test_can_update_recipe_whiteboard(self):
        s = requests.Session()
        requests_login(s, user=self.owner, password=u'theowner')
        response = patch_json(get_server_base() +
                'recipes/%s' % self.recipe.id,
                session=s, data={'whiteboard': u'newwhiteboard'})
        response.raise_for_status()
        with session.begin():
            session.expire_all()
            self.assertEquals(self.recipe.whiteboard, 'newwhiteboard')
            self.assertEquals(self.recipe.activity[0].field_name, u'Whiteboard')
            self.assertEquals(self.recipe.activity[0].action, u'Changed')
            self.assertEquals(self.recipe.activity[0].new_value, u'newwhiteboard')

    def test_anonymous_cannot_update_reservation_request(self):
        response = patch_json(get_server_base() +
                'recipes/%s/reservation-request' % self.recipe_with_reservation_request.id,
                data={'reserve': True, 'duration': 300})
        self.assertEquals(response.status_code, 401)

    def test_cannot_update_reservation_request_on_completed_recipe(self):
        with session.begin():
            data_setup.mark_job_complete(self.job)
        s = requests.Session()
        requests_login(s, user=self.owner, password=u'theowner')
        response = patch_json(get_server_base() +
                'recipes/%s/reservation-request' % self.recipe_with_reservation_request.id,
                session=s, data={'reserve': True, 'duration': False})
        self.assertEquals(response.status_code, 403)

    def test_can_update_reservation_request_to_reserve_system(self):
        with session.begin():
            data_setup.mark_job_running(self.job)
        # On a recipe with reservation request
        s = requests.Session()
        requests_login(s, user=self.owner, password=u'theowner')
        response = patch_json(get_server_base() +
                'recipes/%s/reservation-request' % self.recipe_with_reservation_request.id,
                session=s, data={'reserve': True, 'duration': 300})
        response.raise_for_status()
        with session.begin():
            session.expire_all()
            self.assertEquals(self.recipe_with_reservation_request.reservation_request.duration,
                    300)
            self.assertEquals(self.recipe_with_reservation_request.activity[0].field_name,
                    u'Reservation Request')
            self.assertEquals(self.recipe_with_reservation_request.activity[0].action,
                    u'Changed')
            self.assertEquals(self.recipe_with_reservation_request.activity[0].new_value,
                    u'300')
        # On a recipe without reservation request
        s = requests.Session()
        requests_login(s, user=self.owner, password=u'theowner')
        response = patch_json(get_server_base() +
                'recipes/%s/reservation-request' % self.recipe_without_reservation_request.id,
                session=s, data={'reserve': True, 'duration': 300})
        response.raise_for_status()
        with session.begin():
            session.expire_all()
            self.assertTrue(self.recipe_without_reservation_request.reservation_request)
            self.assertEquals(self.recipe_without_reservation_request.activity[0].field_name,
                    u'Reservation Request')
            self.assertEquals(self.recipe_without_reservation_request.activity[0].action,
                    u'Changed')
            self.assertEquals(self.recipe_without_reservation_request.activity[0].new_value,
                    u'300')

    def test_can_update_reservation_request_to_not_reserve_the_system(self):
        with session.begin():
            data_setup.mark_job_running(self.job)
        s = requests.Session()
        requests_login(s, user=self.owner, password=u'theowner')
        response = patch_json(get_server_base() +
                'recipes/%s/reservation-request' % self.recipe_with_reservation_request.id,
                session=s, data={'reserve': False})
        response.raise_for_status()

        with session.begin():
            session.expire_all()
            self.assertFalse(self.recipe_with_reservation_request.reservation_request)
            self.assertEquals(self.recipe_with_reservation_request.activity[0].field_name,
                    u'Reservation Request')
            self.assertEquals(self.recipe_with_reservation_request.activity[0].action,
                    u'Changed')
            self.assertEquals(self.recipe_with_reservation_request.activity[0].new_value,
                    None)

    def test_anonymous_has_no_reviewed_state(self):
        # Reviewed state is per-user so anonymous should get "reviewed": null 
        # (neither true nor false, since we don't know).
        response = requests.get(get_server_base() +
                'recipes/%s' % self.recipe.id,
                headers={'Accept': 'application/json'})
        response.raise_for_status()
        self.assertEqual(response.json()['reviewed'], None)

    def test_can_clear_reviewed_state(self):
        with session.begin():
            self.recipe.set_reviewed_state(self.owner, True)
        s = requests.Session()
        requests_login(s, user=self.owner, password=u'theowner')
        response = patch_json(get_server_base() + 'recipes/%s' % self.recipe.id,
                session=s, data={'reviewed': False})
        response.raise_for_status()
        with session.begin():
            session.expire_all()
            self.assertEqual(self.recipe.get_reviewed_state(self.owner), False)
