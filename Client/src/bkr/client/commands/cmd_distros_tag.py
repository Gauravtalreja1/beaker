# -*- coding: utf-8 -*-

"""
Tag Beaker distros
==================

.. program:: bkr distros-tag

Synopsis
--------

:program:`bkr distros-tag` [*options*] --name=<name> <tag>

Description
-----------

Applies the given tag to all matching distros in Beaker. Prints to stdout 
a list of the distros which were tagged.

Options
-------

.. option:: --name <name>

   Limit to distros with the given name. <name> is interpreted as a SQL LIKE 
   pattern (the % character matches any substring).

Common :program:`bkr` options are described in the :ref:`Options 
<common-options>` section of :manpage:`bkr(1)`.

Exit status
-----------

Non-zero on error, otherwise zero.

Examples
--------

Tags all RHEL5.6 Server nightly trees from a particular date with the "INSTALLS" tag::

    bkr distros-tag --name RHEL5.6-Server-20101110% INSTALLS

Notes
-----

This command is only available to Beaker administrators.

See also
--------

:manpage:`bkr-distros-untag(1)`, :manpage:`bkr(1)`
"""


from bkr.client import BeakerCommand


class Distros_Tag(BeakerCommand):
    """tag distros"""
    enabled = True


    def options(self):
        self.parser.usage = "%%prog %s [options] <tag>" % self.normalized_name

        self.parser.add_option(
            "--name",
            default=None,
            help="tag by name, use % for wildcard",
        )


    def run(self, *args, **kwargs):
        if len(args) < 1:
            self.parser.error("Please specify a tag")

        username = kwargs.pop("username", None)
        password = kwargs.pop("password", None)
        name = kwargs.pop("name", None)
        tag = args[0]
        if not name:
            self.parser.error('If you really want to tag every distro in Beaker, use --name=%')

        self.set_hub(username, password)
        distros = self.hub.distros.tag(name, tag)
        print "Tagged the following distros with tag: %s" % tag
        print "------------------------------------------------------"
        for distro in distros:
            print distro
