
"""
bkr system-delete: Delete a Beaker system permanently
=====================================================

.. program:: bkr system-delete

Synopsis
--------

:program:`bkr system-delete` [*options*] <fqdn>

Description
-----------

Deletes a Beaker system permanently, but only if the system was never referenced
in any recipes.

Options
-------

Common :program:`bkr` options are described in the :ref:`Options 
<common-options>` section of :manpage:`bkr(1)`.

Exit status
-----------

Non-zero on error, otherwise zero.

Examples
--------

Delete a particular system::

    bkr system-delete system1.example.invalid

See also
--------

:manpage:`bkr(1)`
"""

from bkr.client import BeakerCommand

class System_Delete(BeakerCommand):
    """Delete a system"""
    enabled = True

    def options(self):
        self.parser.usage = "%%prog %s [options] <fqdn>" % self.normalized_name

    def run(self, *args, **kwargs):
        username = kwargs.pop("username", None)
        password = kwargs.pop("password", None)

        if len(args) != 1:
            self.parser.error('Exactly one system fqdn must be given')
        fqdn = args[0]

        self.set_hub(username, password)
        print self.hub.systems.delete(fqdn)
