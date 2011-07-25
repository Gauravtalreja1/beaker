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

import sys
import os
import time
import threading
import subprocess
from StringIO import StringIO
import logging, logging.config
import signal
import cherrypy
import turbogears
from turbogears import update_config
from turbogears.database import session
from bkr.server.controllers import Root
from bkr.server.util import log_to_stream

# hack to make turbogears.testutil not do dumb stuff at import time
orig_cwd = os.getcwd()
os.chdir('/tmp')
import turbogears.testutil
os.chdir(orig_cwd)

# workaround for weird sqlalchemy-0.4 bug :-S
# http://markmail.org/message/rnnzdebfzrjt3kmi
from sqlalchemy.orm.dynamic import DynamicAttributeImpl
DynamicAttributeImpl.accepts_scalar_loader = False

log = logging.getLogger(__name__)

CONFIG_FILE = os.environ.get('BEAKER_CONFIG_FILE', 'server-test.cfg')

def get_server_base():
    return os.environ.get('BEAKER_SERVER_BASE_URL',
        'http://localhost:%s/' % turbogears.config.get('server.socket_port'))

def check_listen(port):
    """
    Returns True iff any process on the system is listening
    on the given TCP port.
    """
    # with newer lsof we could just use -sTCP:LISTEN,
    # but RHEL5's lsof is too old so we have to filter for LISTEN state ourselves
    output, _ = subprocess.Popen(['/usr/sbin/lsof', '-iTCP:%d' % port],
            stdout=subprocess.PIPE).communicate()
    for line in output.splitlines():
        if '(LISTEN)' in line:
            return True
    return False

class Process(object):
    """
    Thin wrapper around subprocess.Popen which supports starting and killing 
    the process in setup/teardown.
    """

    def __init__(self, name, args, env=None, listen_port=None,
            stop_signal=signal.SIGTERM):
        self.name = name
        self.args = args
        self.env = env
        self.listen_port = listen_port
        self.stop_signal = stop_signal

    def start(self):
        log.info('Spawning %s: %s %r', self.name, ' '.join(self.args), self.env)
        env = dict(os.environ)
        if self.env:
            env.update(self.env)
        self.popen = subprocess.Popen(self.args, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, env=env)
        CommunicateThread(popen=self.popen).start()
        if self.listen_port:
            self._wait_for_listen(self.listen_port)

    def _wait_for_listen(self, port):
        """
        Blocks until some process on the system is listening
        on the given TCP port.
        """
        # XXX is there a better way to do this?
        for i in range(20):
            log.info('Waiting for %s to listen on port %d', self.name, port)
            if check_listen(self.listen_port):
                return
            time.sleep(1)
        raise RuntimeError('Gave up waiting for LISTEN %d' % port)

    def stop(self):
        if not hasattr(self, 'popen'):
            log.warning('%s never started, not killing', self.name)
        elif self.popen.poll() is not None:
            log.warning('%s (pid %d) already dead, not killing', self.name, self.popen.pid)
        else:
            log.info('Sending signal %r to %s (pid %d)',
                    self.stop_signal, self.name, self.popen.pid)
            os.kill(self.popen.pid, self.stop_signal)
            self.popen.wait()

class CommunicateThread(threading.Thread):
    """
    Nose has support for capturing stdout during tests, by fiddling with sys.stdout.
    Subprocesses' stdout streams won't be captured that way, however. So for each subprocess
    one of these threads will read from its stdout and write back to sys.stdout
    for nose to capture.
    """

    def __init__(self, popen, **kwargs):
        super(CommunicateThread, self).__init__(**kwargs)
        self.popen = popen

    def run(self):
        while True:
            data = self.popen.stdout.readline()
            if not data: break
            sys.stdout.write(data)

processes = []

def setup_package():
    log.info('Loading test configuration from %s', CONFIG_FILE)
    assert os.path.exists(CONFIG_FILE), 'Config file %s must exist' % CONFIG_FILE
    update_config(configfile=CONFIG_FILE, modulename='bkr.server.config')

    # Override loaded logging config, in case we are using the server's config file
    # (we really always want our tests' logs to go to stdout, not /var/log/beaker/)
    log_to_stream(sys.stdout, level=logging.NOTSET)

    from bkr.inttest import data_setup
    if not 'BEAKER_SKIP_INIT_DB' in os.environ:
        data_setup.setup_model()
        data_setup.create_labcontroller() #always need a labcontroller
    data_setup.create_distro()
    session.flush()

    if not os.path.exists(turbogears.config.get('basepath.rpms')):
        os.mkdir(turbogears.config.get('basepath.rpms'))

    cherrypy.root = Root()
    turbogears.testutil.start_cp()

    if 'BEAKER_SERVER_BASE_URL' not in os.environ:
        # need to start the server ourselves
        # (this only works from the IntegrationTests dir of a Beaker checkout)
        processes.extend([
            Process('beaker', args=['../Server/start-server.py', CONFIG_FILE],
                    listen_port=turbogears.config.get('server.socket_port'),
                    stop_signal=signal.SIGINT)
        ])
    try:
        for process in processes:
            process.start()
    except:
        for process in processes:
            process.stop()
        raise

def teardown_package():
    for process in processes:
        process.stop()

    cherrypy.server.stop()
