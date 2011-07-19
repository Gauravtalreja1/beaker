# -*- coding: utf-8 -*-

"""
Show time remaining on Beaker watchdogs
=======================================

.. program:: bkr watchdog-show

Synopsis
--------

:program:`bkr watchdog-show` [*options*] <task_id>...

Description
-----------

Prints to stdout the watchdog time remaining for one or more recipe-tasks. The 
format of each line of output is ``<task_id>: <seconds>``.

Note that the <task_id> arguments are *not* in the same format as the 
<taskspec> argument accepted by other Beaker commands.

Options
-------

Common :program:`bkr` options are described in the :ref:`Options 
<common-options>` section of :manpage:`bkr(1)`.

Exit status
-----------

Non-zero on error, otherwise zero.

Examples
--------

Show the number of seconds remaining on the watchdog for recipe-task 12345::

    bkr watchdog-show 12345

See also
--------

:manpage:`bkr(1)`
"""

from bkr.client import BeakerCommand
from optparse import OptionValueError


class Watchdog_Show(BeakerCommand):
    """Display Task's Watchdog"""
    enabled = True

    def options(self):
        self.parser.usage = "%%prog %s [options] <task_id>..." % self.normalized_name


    def run(self, *args, **kwargs):
        username = kwargs.pop("username", None)
        password = kwargs.pop("password", None)

        self.set_hub(username, password)
        for task_id in args:
            print "%s: %s" % (task_id, self.hub.recipes.tasks.watchdog(task_id))

