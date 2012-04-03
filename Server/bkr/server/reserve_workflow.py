from turbogears import controllers, identity, expose, url, database, validate, flash, redirect
from turbogears.database import session
from sqlalchemy.sql.expression import and_, func, not_
from sqlalchemy.exceptions import InvalidRequestError
from bkr.server.widgets import ReserveWorkflow as ReserveWorkflowWidget
from bkr.server.widgets import ReserveSystem
from bkr.server.model import (osversion_table, distro_table, osmajor_table, arch_table, distro_tag_table,
                              Distro, Job, RecipeSet, MachineRecipe, System, RecipeTask, RecipeTaskParam,
                              Task, Arch, OSMajor, DistroTag, SystemType, OSVersion, DistroTree)
from bkr.server.model import Job
from bkr.server.jobs import Jobs as JobController
from bexceptions import *
import re
import logging
log = logging.getLogger(__name__)

class ReserveWorkflow:
    widget = ReserveWorkflowWidget(
            action='reserve',
            get_distros_rpc='get_distro_options',
            get_distro_trees_rpc='get_distro_tree_options')
    reserveform = ReserveSystem()
  
    @expose()
    @identity.require(identity.not_anonymous())
    def doit(self, distro_tree_id, **kw):
        """ Create a new reserve job, if system_id is defined schedule it too """
        if 'system_id' in kw:
            kw['id'] = kw['system_id']
         
        try:
            provision_system_job = Job.provision_system_job(distro_tree_id, **kw)
        except BX, msg:
            flash(_(u"%s" % msg))
            redirect(u".")
        JobController.success_redirect(provision_system_job.id)

    @expose(template='bkr.server.templates.form')
    @identity.require(identity.not_anonymous())
    def reserve(self, distro_tree_id, system_id=None):
        """ Either queue or provision the system now """
        if system_id == 'search':
            redirect('/reserve_system', distro_tree_id=distro_tree_id)
        elif system_id:
            try:
                system = System.by_id(system_id, identity.current.user)
            except InvalidRequestError:
                flash(_(u'Invalid System ID %s' % system_id))
            system_name = system.fqdn
        else:
            system_name = 'Any System'
        distro_names = [] 

        return_value = dict(
                            system_id = system_id, 
                            system = system_name,
                            distro = '',
                            distro_tree_ids = [],
                            warn='',
                            )
        if not isinstance(distro_tree_id, list):
            distro_tree_id = [distro_tree_id]
        for id in distro_tree_id:
            try:
                distro_tree = DistroTree.by_id(id)
                if System.by_type(type=SystemType.machine,
                        systems=distro_tree.systems(user=identity.current.user))\
                        .count() < 1:
                    flash(_(u'No systems compatible with %s') % distro_tree)
                distro_names.append(unicode(distro_tree))
                return_value['distro_tree_ids'].append(id)
            except NoResultFound:
                flash(_(u'Invalid distro tree ID %s') % id)
        distro = ", ".join(distro_names)
        return_value['distro'] = distro
        
        return dict(form=self.reserveform,
                    action='./doit',
                    value = return_value,
                    options = None,
                    title='Reserve System %s' % system_name)

    @identity.require(identity.not_anonymous())
    @expose(template='bkr.server.templates.generic') 
    def index(self, **kwargs):
        kwargs.setdefault('tag', 'STABLE')
        value = dict((k, v) for k, v in kwargs.iteritems()
                if k in ['osmajor', 'tag', 'distro'])

        options = {}
        tags = DistroTag.used()
        options['tag'] = [('', 'None selected')] + \
                [(tag.tag, tag.tag) for tag in tags]
        osmajors = sorted(OSMajor.in_any_lab(), key=lambda osmajor:
                re.match(r'(.*?)(\d*)$', osmajor.osmajor).groups())
        options['osmajor'] = [('', 'None selected')] + \
                [(osmajor.osmajor, osmajor.osmajor) for osmajor in osmajors]
        options['distro'] = self._get_distro_options(**kwargs)
        options['distro_tree_id'] = self._get_distro_tree_options(**kwargs)

        attrs = {}
        if not options['distro']:
            attrs['distro'] = dict(disabled=True)

        return dict(title=_(u'Reserve Workflow'),
                    widget=self.widget,
                    value=value,
                    widget_options=options,
                    widget_attrs=attrs)

    @expose(allow_json=True)
    def get_distro_options(self, **kwargs):
        return {'options': self._get_distro_options(**kwargs)}

    def _get_distro_options(self, osmajor=None, tag=None, **kwargs):
        """
        Returns a list of distro names for the given osmajor and tag.
        """
        if not osmajor:
            return []
        distros = Distro.query.join(Distro.osversion, OSVersion.osmajor)\
                .filter(Distro.trees.any(DistroTree.lab_controller_assocs.any()))\
                .filter(OSMajor.osmajor == osmajor)\
                .order_by(Distro.date_created.desc())
        if tag:
            distros = distros.filter(Distro._tags.any(DistroTag.tag == tag))
        return [name for name, in distros.values(Distro.name)]

    @expose(allow_json=True)
    def get_distro_tree_options(self, **kwargs):
        return {'options': self._get_distro_tree_options(**kwargs)}

    def _get_distro_tree_options(self, distro=None, **kwargs):
        """
        Returns a list of distro trees for the given distro.
        """
        if not distro:
            return []
        try:
            distro = Distro.by_name(distro)
        except NoResultFound:
            return []
        trees = distro.dyn_trees.join(DistroTree.arch)\
                .filter(DistroTree.lab_controller_assocs.any())\
                .order_by(DistroTree.variant, Arch.arch)
        return [(tree.id, unicode(tree)) for tree in trees]
