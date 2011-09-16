
"""
Generate Beaker job to test harness installation
================================================

.. program:: bkr harness-test

Synopsis
--------

:program:`bkr harness-test` [*workflow options*] [*options*]

Description
-----------

Generates a Beaker job to test that the harness can be installed correctly on 
all available combinations of distro family, variant, and arch.

This is intended to catch misconfigurations and missing/incomplete harness 
repos, not find bugs in the harness.

Options
-------

Common workflow options are described in the :ref:`Workflow options 
<workflow-options>` section of :manpage:`bkr(1)`.

Common :program:`bkr` options are described in the :ref:`Options 
<common-options>` section of :manpage:`bkr(1)`.

Exit status
-----------

Non-zero on error, otherwise zero.

Examples
--------

Test the harness::

    bkr harness-test

See also
--------

:manpage:`bkr(1)`
"""

try:
    any # builtin in Python 2.5+
except NameError:
    def any(iterable):
        for element in iterable:
            if element:
                return True
        return False

import sys
from bkr.client import BeakerWorkflow, BeakerJob, BeakerRecipeSet, BeakerRecipe

class Harness_Test(BeakerWorkflow):
    """Workflow for testing harness installation"""
    enabled = True

    def options(self):
        super(Harness_Test, self).options()
        self.parser.remove_option("--family")
        self.parser.remove_option("--clients")
        self.parser.remove_option("--servers")
        self.parser.remove_option("--distro")
        self.parser.remove_option("--variant")
        self.parser.remove_option("--arch")
        # Re-add option Family with append options
        self.parser.add_option(
            '--family',
            action='append',
            default=[],
            help='Test harness only on this family'
        )

    def run(self, *args, **kwargs):
        username = kwargs.get('username', None)
        password = kwargs.get('password', None)
        self.set_hub(username, password)

        debug = kwargs.pop('debug', False)
        dryrun = kwargs.pop('dryrun', False)
        wait = kwargs.pop('wait', False)
        taskParams = kwargs.pop('taskparam', [])
        families = kwargs.pop('family', [])
        kwargs.pop('variant', None)
        kwargs.pop('arch', None)

        if not kwargs.get('whiteboard'):
            kwargs['whiteboard'] = 'Test harness installation'

        if not families:
            families = self.getOsMajors(**kwargs)
            # filter out any junky old distros with no family
            families = [f for f in families if f]

        fva = set() # all family-variant-arch combinations
        for family in families:
            distros = self.hub.distros.filter({'family': family})
            for distro in distros:
                arch = distro[2]
                variant = distro[4] or ''
                fva.add((family, variant, arch))
            # if this family has any variants, discard combinations which have blank variant
            if any(f == family and v for f, v, a in fva):
                fva.difference_update([(f, v, a) for f, v, a in fva
                        if f == family and not v])

        job = BeakerJob(**kwargs)
        for family, variant, arch in sorted(fva):
            requestedTasks = [dict(name='/distribution/install', arches=[])]
            requestedTasks.extend(self.getTasks(family=family, **kwargs))
            recipe = BeakerRecipe()
            recipe.addBaseRequires(family=family, variant=variant, arch=arch, **kwargs)
            arch_node = self.doc.createElement('distro_arch')
            arch_node.setAttribute('op', '=')
            arch_node.setAttribute('value', arch)
            recipe = self.processTemplate(recipe, requestedTasks,
                    taskParams=taskParams, distroRequires=arch_node, arch=arch)
            recipe.whiteboard = ' '.join([family, variant, arch])
            recipeset = BeakerRecipeSet(**kwargs)
            recipeset.addRecipe(recipe)
            job.addRecipeSet(recipeset)

        jobxml = job.toxml(**kwargs)

        if debug:
            print jobxml

        submitted_jobs = []
        failed = False

        if not dryrun:
            try:
                submitted_jobs.append(self.hub.jobs.upload(jobxml))
            except Exception, ex:
                failed = True
                print >>sys.stderr, ex
        if not dryrun:
            print "Submitted: %s" % submitted_jobs
            if wait:
                TaskWatcher.watch_tasks(self.hub, submitted_jobs)
            if failed:
                sys.exit(1)
