
import unittest
from turbogears.database import session
from bkr.inttest import data_setup, with_transaction
from bkr.inttest.client import run_client, ClientError

class JobCancelTest(unittest.TestCase):

    @with_transaction
    def setUp(self):
        self.job = data_setup.create_job()

    def test_cannot_cancel_recipe(self):
        try:
            run_client(['bkr', 'job-cancel',
                    self.job.recipesets[0].recipes[0].t_id])
            self.fail('should raise')
        except ClientError, e:
            self.assertEquals(e.status, 1)
            self.assert_('Task type R is not stoppable'
                    in e.stderr_output, e.stderr_output)

    # https://bugzilla.redhat.com/show_bug.cgi?id=595512
    def test_invalid_taskspec(self):
        try:
            run_client(['bkr', 'job-cancel', '12345'])
            fail('should raise')
        except ClientError, e:
            self.assert_('Invalid taskspec' in e.stderr_output)
    # https://bugzilla.redhat.com/show_bug.cgi?id=649608
    def test_cannot_cancel_other_peoples_job(self):
        with session.begin():
            user1 = data_setup.create_user(password='abc')
            job_owner = data_setup.create_user(user_name='user2')
            job = data_setup.create_job(owner=job_owner)

        try:
            run_client(['bkr', 'job-cancel', '--username', user1.user_name, '--password', 'abc', job.t_id])
            self.fail('should raise')
        except ClientError, e:
            self.assertEquals(e.status, 1)
            self.assert_('You don\'t have permission to cancel'
                    in e.stderr_output, e.stderr_output)

