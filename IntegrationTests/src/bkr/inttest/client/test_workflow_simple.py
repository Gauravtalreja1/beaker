import os
import unittest
import subprocess
import re
from threading import Thread
from turbogears.database import session
from bkr.inttest import data_setup, with_transaction
from bkr.inttest.client import run_client, start_client
from bkr.server.model import Job

class WorkflowSimpleTest(unittest.TestCase):

    @with_transaction
    def setUp(self):
        self.distro = data_setup.create_distro(tags=[u'STABLE'])
        self.task = data_setup.create_task()
        data_setup.create_task(name=u'/distribution/install')
        data_setup.create_task(name=u'/distribution/reservesys')

    def test_submit_job(self):
        out = run_client(['bkr', 'workflow-simple', '--random',
                '--arch', self.distro.arch.arch,
                '--family', self.distro.osversion.osmajor.osmajor,
                '--task', self.task.name])
        self.assert_(out.startswith('Submitted:'), out)

    def test_submit_job_wait(self):
        args = ['bkr', 'workflow-simple', '--random',
                '--arch', self.distro.arch.arch,
                '--family', self.distro.osversion.osmajor.osmajor,
                '--task', self.task.name,
                '--wait']
        proc = start_client(args)
        out = proc.stdout.readline().rstrip()
        self.assert_(out.startswith('Submitted:'), out)
        m = re.search('J:(\d+)', out)
        job_id = m.group(1)

        out = proc.stdout.readline().rstrip()
        self.assert_('Watching tasks (this may be safely interrupted)...' == out)

        job = Job.by_id(job_id)
        job.cancel()
        session.flush()
        returncode = proc.wait()
        self.assert_(returncode == 0)

    def test_hostrequire(self):
        out = run_client(['bkr', 'workflow-simple',
                '--dryrun', '--prettyxml',
                '--hostrequire', 'hostlabcontroller=lab.example.com',
                '--arch', self.distro.arch.arch,
                '--family', self.distro.osversion.osmajor.osmajor,
                '--task', self.task.name])
        self.assert_('<hostlabcontroller op="=" value="lab.example.com"/>' in out, out)
