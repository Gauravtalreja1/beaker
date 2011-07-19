# -*- coding: utf-8 -*-

"""
Upload tasks to Beaker's task library
=====================================

.. program:: bkr task-add

Synopsis
--------

:program:`bkr task-add` [*options*] <taskrpm>...

Description
-----------

Uploads one or more task RPM packages to Beaker's task library. These tasks 
will be available for jobs queued with the Beaker scheduler.

If updating an existing task in Beaker, the RPM version of the new package must 
be greater than the version currently in Beaker.

Options
-------

Common :program:`bkr` options are described in the :ref:`Options 
<common-options>` section of :manpage:`bkr(1)`.

Exit status
-----------

XXX FIXME always 0

Examples
--------

Upload a new version of the /distribution/beaker/dogfood task::

    bkr task-add beaker-distribution-beaker-dogfood-2.0-1.rpm

See also
--------

:manpage:`bkr(1)`
"""


from bkr.client.task_watcher import *
from bkr.client import BeakerCommand
from optparse import OptionValueError
import sys
import os.path
import xmlrpclib

class Task_Add(BeakerCommand):
    """Add/Update task to scheduler"""
    enabled = True

    def options(self):
        self.parser.usage = "%%prog %s [options] <taskrpm>..." % self.normalized_name


    def run(self, *args, **kwargs):
        username = kwargs.pop("username", None)
        password = kwargs.pop("password", None)

        tasks = args

        self.set_hub(username, password)
        for task in tasks:
            task_name = os.path.basename(task)
            task_binary = xmlrpclib.Binary(open(task, "r").read())
            print task_name
            try:
                print self.hub.tasks.upload(task_name, task_binary)
            except Exception, ex:
                print ex
