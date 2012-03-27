# -*- coding: utf-8 -*-

"""
Extend Beaker watchdogs time
===========================

.. program:: bkr watchdogs-extend

Synopsis
--------

:program:`bkr watchdogs-extend` [--by=<seconds>] [*options*]

Description
-----------

Extends all the watchdog times that are active.

Options
-------

.. option:: --by <seconds>

   Extend the watchdogs by <seconds>. Default is 7200.

Common :program:`bkr` options are described in the :ref:`Options 
<common-options>` section of :manpage:`bkr(1)`.

Exit status
-----------

Non-zero on error, otherwise zero.

Examples
--------

Extend all the active watchdogs for 1 hour::

    bkr watchdogs-extend --by=3600

See also
--------

:manpage:`bkr(1)`
"""

from bkr.client import BeakerCommand
from optparse import OptionValueError


class Watchdogs_Extend(BeakerCommand):
    """Extend Task's Watchdog"""
    enabled = True

    def options(self):
        self.parser.add_option(
            "--by",
            default=7200, type="int",
            help="Time in seconds to extend the watchdog by.",
        )

        self.parser.usage = "%%prog %s [options]" % self.normalized_name


    def run(self, *args, **kwargs):
        username = kwargs.pop("username", None)
        password = kwargs.pop("password", None)
        extend_by = kwargs.pop("by", None)

        self.set_hub(username, password)
        print self.hub.watchdogs.extend(extend_by)

