
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import datetime
from turbogears.database import session
from turbogears import expose, flash, widgets, validate, validators, redirect, paginate, url
from cherrypy import response
from formencode.api import Invalid
from sqlalchemy import and_
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm.exc import NoResultFound
from bkr.server.widgets import myPaginateDataGrid, \
    SearchBar, JobActionWidget, \
    HorizontalForm, BeakerDataGrid
from bkr.server.xmlrpccontroller import RPCRoot
from bkr.server.helpers import make_link
from bkr.server.junitxml import to_junit_xml
from bkr.server import search_utility, identity, metrics
from bkr.server.needpropertyxml import XmlHost
from bkr.server.installopts import InstallOptions
from bkr.server.controller_utilities import _custom_status, _custom_result, \
    restrict_http_method
from bkr.server.app import app
import pkg_resources
import lxml.etree
import logging

import cherrypy

from bkr.server.model import (Job, RecipeSet, RetentionTag, TaskBase,
                              TaskPriority, User, Group, MachineRecipe,
                              DistroTree, TaskPackage, RecipeRepo,
                              RecipeKSAppend, Task, Product, GuestRecipe,
                              RecipeTask, RecipeTaskParam,
                              StaleTaskStatusException,
                              RecipeSetActivity, System, RecipeReservationRequest,
                              TaskStatus, RecipeSetComment)

from bkr.common.bexceptions import BeakerException, BX
from bkr.server.flask_util import auth_required, convert_internal_errors, \
    BadRequest400, NotFound404, Forbidden403, Conflict409, request_wants_json, \
    read_json_request, render_tg_template
from flask import request, jsonify, make_response
from bkr.server.util import parse_untrusted_xml
import cgi
from bkr.server.job_utilities import Utility


log = logging.getLogger(__name__)

__all__ = ['JobForm', 'Jobs']

class JobForm(widgets.Form):

    template = 'bkr.server.templates.job_form'
    name = 'job'
    submit_text = _(u'Queue')
    fields = [widgets.TextArea(name='textxml')]
    hidden_fields = [widgets.HiddenField(name='confirmed', validator=validators.StringBool())]
    params = ['xsd_errors']
    xsd_errors = None

    def update_params(self, d):
        super(JobForm, self).update_params(d)
        if 'xsd_errors' in d['options']:
            d['xsd_errors'] = d['options']['xsd_errors']
            d['submit_text'] = _(u'Queue despite validation errors')

class Jobs(RPCRoot):
    # For XMLRPC methods in this class.
    exposed = True 
    job_list_action_widget = JobActionWidget()

    _upload = widgets.FileField(name='filexml', label='Job XML')
    form = HorizontalForm(
        'jobs',
        fields = [_upload],
        action = 'save_data',
        submit_text = _(u'Submit Data')
    )
    del _upload

    job_form = JobForm()

    job_schema_doc = lxml.etree.parse(pkg_resources.resource_stream(
            'bkr.common', 'schema/beaker-job.rng'))

    @classmethod
    def success_redirect(cls, id, url='/jobs/mine', *args, **kw):
        flash(_(u'Success! job id: %s' % id))
        redirect('%s' % url)

    @expose(template='bkr.server.templates.form-post')
    @identity.require(identity.not_anonymous())
    def new(self, **kw):
        return dict(
            title = 'New Job',
            form = self.form,
            action = './clone',
            options = {},
            value = kw,
        )

    def _check_job_deletability(self, t_id, job):
        if not isinstance(job, Job):
            raise TypeError('%s is not of type %s' % (t_id, Job.__name__))
        if not job.can_delete(identity.current.user):
            raise BeakerException(_(u'You do not have permission to delete %s' % t_id))

    def _delete_job(self, t_id):
        job = TaskBase.get_by_t_id(t_id)
        self._check_job_deletability(t_id, job)
        Job.delete_jobs([job])
        return [t_id]

    @expose()
    @identity.require(identity.not_anonymous())
    @restrict_http_method('post')
    def delete_job_row(self, t_id):
        try:
            self._delete_job(t_id)
            return [t_id]
        except (BeakerException, TypeError), e:
            log.debug(str(e))
            response.status = 400
            return ['Unable to delete %s' % t_id]

    @cherrypy.expose
    def list(self, tags, days_complete_for, family, product, **kw):
        """
        Lists Jobs, filtered by the given criteria.
        :param tags: limit to recipe sets which have one of these retention tags
        :type tags: string or array of strings
        :param days_complete_for: limit to recipe sets which completed at least this many days ago
        :type days_complete_for: integer
        :param family: limit to recipe sets which used distros with this family name
        :type family: string

        Returns a two-element array. The first element is an array of JobIDs
        of the form ``'J:123'``, suitable to be passed to the
        :meth:`jobs.delete_jobs` method. The second element is a human-readable
        count of the number of Jobs matched. Does not return deleted jobs.

        .. deprecated:: 0.9.4
            Use :meth:`jobs.filter` instead.
        """

        jobs = {'tags':tags,
                'daysComplete':days_complete_for,
                'family':family,
                'product':product}

        return self.filter(jobs)

    @cherrypy.expose
    def filter(self, filters):
        """
        Returns a list of details for jobs filtered by the given criteria.

        The *filter* argument must be a an XML-RPC structure (dict) specifying
        filter criteria. The following keys are recognised:

            'tags'
                List of job tags.
            'daysComplete'
                Number of days elapsed since the jobs completion.
            'family'
                Job distro family, for example ``'RedHatEnterpriseLinuxServer5'``.
            'product'
                Job product name
            'owner'
                Job owner username
            'mine'
                Inclusion is equivalent to including own username in 'owner'
            'whiteboard'
                Job whiteboard (substring match)
            'limit'
                Integer limit to number of jobs returned.
            'minid'
                Min JobID of the jobs to search
            'maxid'
                Maximum Job ID of the jobs to search

        Returns an array of JobIDs of the form ``'J:123'``, suitable to be passed
        to the :meth:`jobs.delete_jobs` method. Does not return deleted jobs.
        """

        # if  min/max/both IDs have been specified, filter it right here
        minid = filters.get('minid', None)
        maxid = filters.get('maxid', None)
        jobs = session.query(Job)
        if minid:
            jobs = jobs.filter(Job.id >= minid)
        if maxid:
            jobs = jobs.filter(Job.id <= maxid)

        tags = filters.get('tags', None)
        complete_days = filters.get('daysComplete', None)
        family = filters.get('family', None)
        product = filters.get('product', None)
        owner = filters.get('owner', None)
        whiteboard = filters.get('whiteboard', None)
        mine = filters.get('mine', None)
        limit = filters.get('limit', None)

        if mine and not identity.not_anonymous():
            raise BX(_('You should be authenticated to use the --mine filter.'))

        if mine and identity.not_anonymous():
            if owner:
                if type(owner) is list:
                    owner.append(identity.current.user.user_name)
                else:
                    owner = [owner, identity.current.user.user_name]
            else:
                owner = identity.current.user.user_name

        jobs = jobs.order_by(Job.id.desc())
        if tags:
            jobs = Job.by_tag(tags, jobs)
        if complete_days:
            jobs = Job.complete_delta({'days':int(complete_days)}, jobs)
        if family:
            jobs = Job.has_family(family, jobs)
        if product:
            jobs = Job.by_product(product, jobs)
        if owner:
            jobs = Job.by_owner(owner, jobs)
        if whiteboard:
            jobs = jobs.filter(Job.whiteboard.like(u'%%%s%%' % whiteboard))

        jobs = Job.sanitise_jobs(jobs)

        if limit:
            limit = int(limit)
            jobs = jobs.limit(limit)

        jobs = jobs.values(Job.id)
        
        return_value = ['J:%s' % j[0] for j in jobs]
        return return_value

    @cherrypy.expose
    @identity.require(identity.not_anonymous())
    def delete_jobs(self, jobs=None, tag=None, complete_days=None, family=None, dryrun=False, product=None):
        """
        delete_jobs will mark the job to be deleted

        To select jobs by id, pass an array for the *jobs* argument. Elements
        of the array must be strings of the form ``'J:123'``.
        Alternatively, pass some combination of the *tag*, *complete_days*, or
        *family* arguments to select jobs for deletion. These arguments behave
        as per the :meth:`jobs.list` method.

        If *dryrun* is True, deletions will be reported but nothing will be
        modified.

        Admins are not be able to delete jobs which are not owned by
        themselves by using the tag, complete_days etc kwargs, instead, they
        should do that via the *jobs* argument.
        """
        if jobs: #Turn them into job objects
            if not isinstance(jobs,list):
                jobs = [jobs]
            jobs_to_try_to_del = []
            for j_id in jobs:
                job = TaskBase.get_by_t_id(j_id)
                if not isinstance(job,Job):
                    raise BeakerException('Incorrect task type passed %s' % j_id )
                if not job.can_delete(identity.current.user):
                    raise BeakerException("You don't have permission to delete job %s" % j_id)
                jobs_to_try_to_del.append(job)
            delete_jobs_kw = dict(jobs=jobs_to_try_to_del)
        else:
            # only allow people to delete their own jobs while using these kwargs
            delete_jobs_kw = dict(query=Job.find_jobs(tag=tag,
                complete_days=complete_days,
                family=family, product=product,
                owner=identity.current.user.user_name))

        deleted_jobs = Job.delete_jobs(**delete_jobs_kw)

        msg = 'Jobs deleted'
        if dryrun:
            session.rollback()
            msg = 'Dryrun only. %s' % (msg)
        return '%s: %s' % (msg, [j.t_id for j in deleted_jobs])

    # XMLRPC method
    @cherrypy.expose
    @identity.require(identity.not_anonymous())
    def upload(self, jobxml, ignore_missing_tasks=False):
        """
        Queues a new job.

        :param jobxml: XML description of job to be queued
        :type jobxml: string
        :param ignore_missing_tasks: pass True for this parameter to cause 
            unknown tasks to be silently discarded (default is False)
        :type ignore_missing_tasks: bool
        """
        if isinstance(jobxml, unicode):
            jobxml = jobxml.encode('utf8')
        xmljob = parse_untrusted_xml(jobxml)
        job = self.process_xmljob(xmljob, identity.current.user,
                                  ignore_missing_tasks=ignore_missing_tasks)
        session.flush()  # so that we get an id
        return "J:%s" % job.id

    @identity.require(identity.not_anonymous())
    @expose(template="bkr.server.templates.form-post")
    @validate(validators={'confirmed': validators.StringBool()})
    def clone(self, job_id=None, recipe_id=None, recipeset_id=None,
            textxml=None, filexml=None, confirmed=False, **kw):
        """
        Review cloned xml before submitting it.
        """
        title = 'Clone Job'
        if job_id:
            # Clone from Job ID
            title = 'Clone Job %s' % job_id
            try:
                job = Job.by_id(job_id)
            except InvalidRequestError:
                flash(_(u"Invalid job id %s" % job_id))
                redirect(".")
            textxml = lxml.etree.tostring(job.to_xml(clone=True), pretty_print=True)
        elif recipeset_id:
            title = 'Clone Recipeset %s' % recipeset_id
            try:
                recipeset = RecipeSet.by_id(recipeset_id)
            except InvalidRequestError:
                flash(_(u"Invalid recipeset id %s" % recipeset_id))
                redirect(".")
            textxml = lxml.etree.tostring(recipeset.to_xml(clone=True,from_job=False),
                                          pretty_print=True)
        elif isinstance(filexml, cgi.FieldStorage):
            # Clone from file
            try:
                textxml = filexml.value.decode('utf8')
            except UnicodeDecodeError, e:
                flash(_(u'Invalid job XML: %s') % e)
                redirect('.')
        elif textxml:
            try:
                # xml.sax (and thus, xmltramp) expect raw bytes, not unicode
                textxml = textxml.encode('utf8')
                if not confirmed:
                    job_schema = lxml.etree.RelaxNG(self.job_schema_doc)
                    if not job_schema.validate(lxml.etree.fromstring(textxml)):
                        log.debug('Job failed validation, with errors: %r',
                                job_schema.error_log)
                        return dict(
                            title = title,
                            form = self.job_form,
                            action = 'clone',
                            options = {'xsd_errors': job_schema.error_log},
                            value = dict(textxml=textxml, confirmed=True),
                        )
                xmljob = parse_untrusted_xml(textxml)
                job = self.process_xmljob(xmljob, identity.current.user)
                session.flush()
            except Exception,err:
                session.rollback()
                flash(_(u'Failed to import job because of: %s' % err))
                return dict(
                    title = title,
                    form = self.job_form,
                    action = './clone',
                    options = {},
                    value = dict(textxml = "%s" % textxml, confirmed=confirmed),
                )
            else:
                self.success_redirect(job.id)
        return dict(
            title = title,
            form = self.job_form,
            action = './clone',
            options = {},
            value = dict(textxml = "%s" % textxml, confirmed=confirmed),
        )


    def _handle_recipe_set(self, xmlrecipeSet, user, ignore_missing_tasks=False):
        """
        Handles the processing of recipesets into DB entries from their xml
        """
        recipeSet = RecipeSet(ttasks=0)
        recipeset_priority = xmlrecipeSet.get('priority')
        if recipeset_priority is not None:
            try:
                my_priority = TaskPriority.from_string(recipeset_priority)
            except InvalidRequestError:
                raise BX(_('You have specified an invalid recipeSet priority:%s' % recipeset_priority))
            allowed_priorities = RecipeSet.allowed_priorities_initial(user)
            if my_priority in allowed_priorities:
                recipeSet.priority = my_priority
            else:
                recipeSet.priority = TaskPriority.default_priority()
        else:
            recipeSet.priority = TaskPriority.default_priority()

        for xmlrecipe in xmlrecipeSet.iter('recipe'):
            recipe = self.handleRecipe(xmlrecipe, user,
                                       ignore_missing_tasks=ignore_missing_tasks)
            recipe.ttasks = len(recipe.tasks)
            recipeSet.ttasks += recipe.ttasks
            recipeSet.recipes.append(recipe)
            # We want the guests to be part of the same recipeSet
            for guest in recipe.guests:
                recipeSet.recipes.append(guest)
                guest.ttasks = len(guest.tasks)
                recipeSet.ttasks += guest.ttasks
        if not recipeSet.recipes:
            raise BX(_('No Recipes! You can not have a recipeSet with no recipes!'))
        return recipeSet

    def _process_job_tag_product(self, retention_tag=None, product=None, *args, **kw):
        """
        Process job retention_tag and product
        """
        retention_tag = retention_tag or RetentionTag.get_default().tag
        try:
            tag = RetentionTag.by_tag(retention_tag.lower())
        except InvalidRequestError:
            raise BX(_("Invalid retention_tag attribute passed. Needs to be one of %s. You gave: %s" % (','.join([x.tag for x in RetentionTag.get_all()]), retention_tag)))
        if product is None and tag.requires_product():
            raise BX(_("You've selected a tag which needs a product associated with it, \
            alternatively you could use one of the following tags %s" % ','.join([x.tag for x in RetentionTag.get_all() if not x.requires_product()])))
        elif product is not None and not tag.requires_product():
            raise BX(_("Cannot specify a product with tag %s, please use %s as a tag " % (retention_tag,','.join([x.tag for x in RetentionTag.get_all() if x.requires_product()]))))
        else:
            pass

        if tag.requires_product():
            try:
                product = Product.by_name(product)

                return (tag, product)
            except ValueError:
                raise BX(_("You entered an invalid product name: %s" % product))
        else:
            return tag, None

    def process_xmljob(self, xmljob, user, ignore_missing_tasks=False):
        # We start with the assumption that the owner == 'submitting user', until
        # we see otherwise.
        submitter = user
        if user.rootpw_expired:
            raise BX(_('Your root password has expired, please change or clear it in order to submit jobs.'))
        owner_name = xmljob.get('user')
        if owner_name:
            owner = User.by_user_name(owner_name)
            if owner is None:
                raise ValueError('%s is not a valid user name' % owner_name)
            if not submitter.is_delegate_for(owner):
                raise ValueError('%s is not a valid submission delegate for %s' % (submitter, owner))
        else:
            owner = user

        group_name = xmljob.get('group')
        group = None
        if group_name:
            try:
                group = Group.by_name(group_name)
            except NoResultFound, e:
                raise ValueError('%s is not a valid group' % group_name)
            if group not in owner.groups:
                raise BX(_(u'User %s is not a member of group %s' % (owner.user_name, group.group_name)))
        job_retention = xmljob.get('retention_tag')
        job_product = xmljob.get('product')
        tag, product = self._process_job_tag_product(retention_tag=job_retention, product=job_product)
        job = Job(whiteboard=xmljob.findtext('whiteboard', default=''),
                  ttasks=0,
                  owner=owner,
                  group=group,
                  submitter=submitter,
                  )
        extra_xml = xmljob.xpath('*[namespace-uri()]')
        if extra_xml is not None:
            job.extra_xml = u''.join([lxml.etree.tostring(x).strip() for x in extra_xml])
        job.product = product
        job.retention_tag = tag
        email_validator = validators.Email(not_empty=True)
        for addr in xmljob.xpath('notify/cc'):
            try:
                addr = email_validator.to_python(addr.text.strip())
                if addr not in job.cc:
                    job.cc.append(addr)
            except Invalid, e:
                raise BX(_('Invalid e-mail address %r in <cc/>: %s') % (addr, str(e)))
        for xmlrecipeSet in xmljob.iter('recipeSet'):
            recipe_set = self._handle_recipe_set(xmlrecipeSet, owner,
                                                 ignore_missing_tasks=ignore_missing_tasks)
            job.recipesets.append(recipe_set)
            job.ttasks += recipe_set.ttasks

        if not job.recipesets:
            raise BX(_('No RecipeSets! You can not have a Job with no recipeSets!'))
        session.add(job)
        metrics.measure('counters.recipes_submitted', len(list(job.all_recipes)))
        return job

    def _jobs(self,job,**kw):
        return_dict = {}
        # We can do a quick search, or a regular simple search. If we have done neither of these,
        # it will fall back to an advanced search and look in the 'jobsearch'

        # simplesearch set to None will display the advanced search, otherwise in the simplesearch
        # textfield it will display the value assigned to it
        simplesearch = None
        if kw.get('simplesearch'):
            value = kw['simplesearch']
            kw['jobsearch'] = [{'table' : 'Id',
                                 'operation' : 'is',
                                 'value' : value}]
            simplesearch = value
        if kw.get("jobsearch"):
            if 'quick_search' in kw['jobsearch']:
                table,op,value = kw['jobsearch']['quick_search'].split('-')
                kw['jobsearch'] = [{'table' : table,
                                    'operation' : op,
                                    'value' : value}]
                simplesearch = ''
            log.debug(kw['jobsearch'])
            searchvalue = kw['jobsearch']
            jobs_found = self._job_search(job,**kw)
            return_dict.update({'jobs_found':jobs_found})
            return_dict.update({'searchvalue':searchvalue})
            return_dict.update({'simplesearch':simplesearch})
        return return_dict

    def _job_search(self,task,**kw):
        job_search = search_utility.Job.search(task)
        for search in kw['jobsearch']:
            col = search['table'] 
            job_search.append_results(search['value'],col,search['operation'],**kw)
        return job_search.return_results()

    def handleRecipe(self, xmlrecipe, user, guest=False, ignore_missing_tasks=False):
        if not guest:
            recipe = MachineRecipe(ttasks=0)
            for xmlguest in xmlrecipe.iter('guestrecipe'):
                guestrecipe = self.handleRecipe(xmlguest, user, guest=True,
                                                ignore_missing_tasks=ignore_missing_tasks)
                recipe.guests.append(guestrecipe)
        else:
            recipe = GuestRecipe(ttasks=0)
            recipe.guestname = xmlrecipe.get('guestname')
            recipe.guestargs = xmlrecipe.get('guestargs')
        recipe.host_requires = lxml.etree.tostring(xmlrecipe.find('hostRequires'))
        recipe.distro_requires = lxml.etree.tostring(xmlrecipe.find('distroRequires'))

        partitions = xmlrecipe.find('partitions')
        if partitions is not None:
            recipe.partitions = lxml.etree.tostring(partitions)

        try:
            recipe.distro_tree = DistroTree.by_filter("%s" % recipe.distro_requires)[0]
        except IndexError:
            raise BX(_('No distro tree matches Recipe: %s') % recipe.distro_requires)
        try:
            # try evaluating the host_requires, to make sure it's valid
            XmlHost.from_string(recipe.host_requires).apply_filter(System.query)
        except StandardError, e:
            raise BX(_('Error in hostRequires: %s' % e))
        recipe.whiteboard = xmlrecipe.get('whiteboard')
        recipe.kickstart = xmlrecipe.findtext('kickstart')

        autopick = xmlrecipe.find('autopick')
        if autopick is not None:
            random = autopick.get('random', '')
            if random.lower() in ('true', '1'):
                recipe.autopick_random = True
            else:
                recipe.autopick_random = False
        watchdog = xmlrecipe.find('watchdog')
        if watchdog is not None:
            recipe.panic = watchdog.get('panic', u'None')
        recipe.ks_meta = xmlrecipe.get('ks_meta')
        recipe.kernel_options = xmlrecipe.get('kernel_options')
        recipe.kernel_options_post = xmlrecipe.get('kernel_options_post')
        # try parsing install options to make sure there is no syntax error
        try:
            InstallOptions.from_strings(recipe.ks_meta,
                                        recipe.kernel_options, recipe.kernel_options_post)
        except Exception as e:
            raise BX(_('Error parsing ks_meta: %s' % e))
        recipe.role = xmlrecipe.get('role', u'None')

        reservesys = xmlrecipe.find('reservesys')
        if reservesys is not None:
            duration = reservesys.get('duration', 86400)
            recipe.reservation_request = RecipeReservationRequest(int(duration))

        custom_packages = set()
        for xmlpackage in xmlrecipe.xpath('packages/package'):
            package = TaskPackage.lazy_create(package='%s' % xmlpackage.get('name', u'None'))
            custom_packages.add(package)
        for installPackage in xmlrecipe.iter('installPackage'):
            package = TaskPackage.lazy_create(package='%s' % installPackage.text)
            custom_packages.add(package)
        recipe.custom_packages = list(custom_packages)
        for xmlrepo in xmlrecipe.xpath('repos/repo'):
            recipe.repos.append(
                RecipeRepo(name=xmlrepo.get('name', u'None'), url=xmlrepo.get('url', u'None'))
            )

        for xmlksappend in xmlrecipe.xpath('ks_appends/ks_append'):
            recipe.ks_appends.append(RecipeKSAppend(ks_append=xmlksappend.text))
        xmltasks = []
        invalid_tasks = []
        for xmltask in xmlrecipe.xpath('task'):
            if xmltask.xpath('fetch'):
                # If fetch URL is given, the task doesn't need to exist.
                xmltasks.append(xmltask)
            elif Task.exists_by_name(xmltask.get('name'), valid=True):
                xmltasks.append(xmltask)
            else:
                invalid_tasks.append(xmltask.get('name', ''))
        if invalid_tasks and not ignore_missing_tasks:
            raise BX(_('Invalid task(s): %s') % ', '.join(invalid_tasks))
        for xmltask in xmltasks:
            fetch = xmltask.find('fetch')
            if fetch is not None:
                recipetask = RecipeTask.from_fetch_url(
                    fetch.get('url'), subdir=fetch.get('subdir', u''), name=xmltask.get('name'))
            else:
                recipetask = RecipeTask.from_task(Task.by_name(xmltask.get('name')))
            recipetask.role = xmltask.get('role', u'None')
            for xmlparam in xmltask.xpath('params/param'):
                param = RecipeTaskParam(name=xmlparam.get('name', u'None'),
                                        value=xmlparam.get('value', u'None'))
                recipetask.params.append(param)
            recipe.tasks.append(recipetask)
        if not recipe.tasks:
            raise BX(_('No Tasks! You can not have a recipe with no tasks!'))
        return recipe

    @cherrypy.expose
    @identity.require(identity.not_anonymous())
    def set_retention_product(self, job_t_id, retention_tag_name, product_name):
        """
        XML-RPC method to update a job's retention tag, product, or both.

        There is an important distinction between product_name of None, which 
        means do not change the existing value, vs. empty string, which means 
        clear the existing product.
        """
        job = TaskBase.get_by_t_id(job_t_id)
        if job.can_change_product(identity.current.user) and \
            job.can_change_retention_tag(identity.current.user):
            if retention_tag_name and product_name:
                retention_tag = RetentionTag.by_name(retention_tag_name)
                product = Product.by_name(product_name)
                old_tag = job.retention_tag if job.retention_tag else None
                result = Utility.update_retention_tag_and_product(job,
                                                                  retention_tag, product)
                job.record_activity(user=identity.current.user, service=u'XMLRPC',
                                    field=u'Retention Tag', action='Changed',
                                    old=old_tag.tag, new=retention_tag.tag)
            elif retention_tag_name and product_name == '':
                retention_tag = RetentionTag.by_name(retention_tag_name)
                old_tag = job.retention_tag if job.retention_tag else None
                result = Utility.update_retention_tag_and_product(job,
                                                                  retention_tag, None)
                job.record_activity(user=identity.current.user, service=u'XMLRPC',
                                    field=u'Retention Tag', action='Changed',
                                    old=old_tag.tag, new=retention_tag.tag)
            elif retention_tag_name:
                retention_tag = RetentionTag.by_name(retention_tag_name)
                old_tag = job.retention_tag if job.retention_tag else None
                result = Utility.update_retention_tag(job, retention_tag)
                job.record_activity(user=identity.current.user, service=u'XMLRPC',
                                    field=u'Retention Tag', action='Changed',
                                    old=old_tag.tag, new=retention_tag.tag)
            elif product_name:
                product = Product.by_name(product_name)
                result = Utility.update_product(job, product)
            elif product_name == '':
                result = Utility.update_product(job, None)
            else:
                result = {'success': False, 'msg': 'Nothing to do'}

            if not result['success'] is True:
                raise BeakerException('Job %s not updated: %s' % (job.id, result.get('msg', 'Unknown reason')))
        else:
            raise BeakerException('No permission to modify %s' % job)


    @cherrypy.expose
    @identity.require(identity.not_anonymous())
    def set_response(self, taskid, response):
        """
        Updates the response (ack/nak) for a recipe set, or for all recipe sets 
        in a job.

        Deprecated: setting 'nak' is a backwards compatibility alias for 
        waiving a recipe set. Use the JSON API to set {waived: true} instead.

        :param taskid: see above
        :type taskid: string
        :param response: new response, either ``'ack'`` or ``'nak'``
        :type response: string
        """
        job = TaskBase.get_by_t_id(taskid)
        if not job.can_waive(identity.current.user):
            raise BeakerException('No permission to modify %s' % job)
        if response == 'nak':
            waived = True
        elif response == 'ack':
            waived = False
        else:
            raise ValueError('Unrecognised response %r' % response)
        job.set_waived(waived)

    @cherrypy.expose
    @identity.require(identity.not_anonymous())
    def stop(self, job_id, stop_type, msg=None):
        """
        Set job status to Completed
        """
        try:
            job = Job.by_id(job_id)
        except InvalidRequestError:
            raise BX(_('Invalid job ID: %s' % job_id))
        if stop_type not in job.stop_types:
            raise BX(_('Invalid stop_type: %s, must be one of %s' %
                             (stop_type, job.stop_types)))
        kwargs = dict(msg = msg)
        return getattr(job,stop_type)(**kwargs)

    @expose(template='bkr.server.templates.grid')
    @paginate('list',default_order='-id', limit=50)
    def index(self,*args,**kw): 
        return self.jobs(jobs=session.query(Job).join('owner'),*args,**kw)

    @identity.require(identity.not_anonymous())
    @expose(template='bkr.server.templates.grid')
    @paginate('list',default_order='-id', limit=50)
    def mine(self, *args, **kw):
        query = Job.mine(identity.current.user)
        return self.jobs(jobs=query, action='./mine', title=u'My Jobs', *args, **kw)

    @identity.require(identity.not_anonymous())
    @expose(template='bkr.server.templates.grid')
    @paginate('list',default_order='-id', limit=50)
    def mygroups(self, *args, **kw):
        query = Job.my_groups(identity.current.user)
        return self.jobs(jobs=query, action='./mygroups', title=u'My Group Jobs',
                *args, **kw)

    def jobs(self,jobs,action='.', title=u'Jobs', *args, **kw):
        jobs = jobs.filter(and_(Job.deleted == None, Job.to_delete == None))
        jobs_return = self._jobs(jobs, **kw)
        searchvalue = None
        search_options = {}
        if jobs_return:
            if 'jobs_found' in jobs_return:
                jobs = jobs_return['jobs_found']
            if 'searchvalue' in jobs_return:
                searchvalue = jobs_return['searchvalue']
            if 'simplesearch' in jobs_return:
                search_options['simplesearch'] = jobs_return['simplesearch']

        def get_group(x):
            if x.group:
                return make_link(url = '../groups/edit?group_id=%d' % x.group.group_id, text=x.group.group_name)
            else:
                return None

        PDC = widgets.PaginateDataGrid.Column
        jobs_grid = myPaginateDataGrid(
            fields=[
                PDC(name='id',
                    getter=lambda x:make_link(url = './%s' % x.id, text = x.t_id),
                    title='ID', options=dict(sortable=True)),
                PDC(name='whiteboard',
                    getter=lambda x:x.whiteboard, title='Whiteboard',
                    options=dict(sortable=True)),
                PDC(name='group',
                    getter=get_group, title='Group',
                    options=dict(sortable=True)),
                PDC(name='owner',
                    getter=lambda x:x.owner.email_link, title='Owner',
                    options=dict(sortable=True)),
                PDC(name='progress',
                    getter=lambda x: x.progress_bar, title='Progress',
                    options=dict(sortable=False)),
                PDC(name='status',
                    getter= _custom_status, title='Status',
                    options=dict(sortable=True)),
                PDC(name='result',
                    getter=_custom_result, title='Result',
                    options=dict(sortable=True)),
                PDC(name='action',
                    getter=lambda x: \
                        self.job_list_action_widget.display(
                        task=x, type_='joblist',
                        delete_action=url('/jobs/delete_job_row'),
                        export=url('/to_xml?taskid=%s' % x.t_id),
                        title='Action', options=dict(sortable=False)))])

        search_bar = SearchBar(name='jobsearch',
                           label=_(u'Job Search'),    
                           simplesearch_label = 'Lookup ID',
                           table = search_utility.Job.search.create_complete_search_table(without=('Owner')),
                           search_controller=url("/get_search_options_job"),
                           quick_searches = [('Status-is-Queued','Queued'),('Status-is-Running','Running'),('Status-is-Completed','Completed')])
                            

        return dict(title=title,
                    grid=jobs_grid,
                    list=jobs,
                    action_widget = self.job_list_action_widget,  #Hack,inserts JS for us.
                    search_bar=search_bar,
                    action=action,
                    options=search_options,
                    searchvalue=searchvalue)

def _get_job_by_id(id):
    """Get job by ID, reporting HTTP 404 if the job is not found"""
    try:
        return Job.by_id(id)
    except NoResultFound:
        raise NotFound404('Job not found')

@app.route('/jobs/<int:id>', methods=['GET'])
def get_job(id):
    """
    Provides detailed information about a job in JSON format.

    :param id: ID of the job.
    """
    job = _get_job_by_id(id)
    if request_wants_json():
        return jsonify(job.__json__())
    return render_tg_template('bkr.server.templates.job', {
        'title': job.t_id, # N.B. JobHeaderView in JS updates the page title
        'job': job,
    })

@app.route('/jobs/<int:id>.xml', methods=['GET'])
def job_xml(id):
    """
    Returns the job in Beaker results XML format.

    :status 200: The job xml file was successfully generated.
    """
    job = _get_job_by_id(id)
    xmlstr = lxml.etree.tostring(job.to_xml(), pretty_print=True)
    response = make_response(xmlstr)
    response.status_code = 200
    response.headers.add('Content-Type', 'text/xml')
    return response

@app.route('/jobs/<int:id>.junit.xml', methods=['GET'])
def job_junit_xml(id):
    """
    Returns the job in JUnit-compatible XML format.
    """
    job = _get_job_by_id(id)
    response = make_response(to_junit_xml(job))
    response.status_code = 200
    response.headers.add('Content-Type', 'text/xml')
    return response

@app.route('/jobs/<int:id>', methods=['PATCH'])
@auth_required
def update_job(id):
    """
    Updates metadata of an existing job including retention settings and comments.
    The request body must be a JSON object containing one or more of the following
    keys.

    :param id: Job's id.
    :jsonparam string retention_tag: Retention tag of the job.
    :jsonparam string product: Product of the job.
    :jsonparam string whiteboard: Whiteboard of the job.
    :status 200: Job was updated.
    :status 400: Invalid data was given.
    """
    job = _get_job_by_id(id)
    if not job.can_edit(identity.current.user):
        raise Forbidden403('Cannot edit job %s' % job.id)
    data = read_json_request(request)
    def record_activity(field, old, new, action=u'Changed'):
        job.record_activity(user=identity.current.user, service=u'HTTP',
                action=action, field=field, old=old, new=new)
    with convert_internal_errors():
        if 'whiteboard' in data:
            new_whiteboard = data['whiteboard']
            if new_whiteboard != job.whiteboard:
                record_activity(u'Whiteboard', job.whiteboard, new_whiteboard)
                job.whiteboard = new_whiteboard
        if 'retention_tag' in data:
            retention_tag = RetentionTag.by_name(data['retention_tag'])
            if retention_tag.requires_product() and not data.get('product') and not job.product:
                raise BadRequest400('Cannot change retention tag as it requires a product')
            if not retention_tag.requires_product() and (data.get('product') or
                    'product' not in data and job.product):
                raise BadRequest400('Cannot change retention tag as it does not support a product')
            if retention_tag != job.retention_tag:
                record_activity(u'Retention Tag', job.retention_tag, retention_tag)
                job.retention_tag = retention_tag
        if 'product' in data:
            if data['product'] is None:
                product = None
                if job.retention_tag.requires_product():
                    raise BadRequest400('Cannot change product as the current '
                            'retention tag requires a product')
            else:
                product = Product.by_name(data['product'])
                if not job.retention_tag.requires_product():
                    raise BadRequest400('Cannot change product as the current '
                            'retention tag does not support a product')
            if product != job.product:
                record_activity(u'Product', job.product, product)
                job.product = product
        if 'cc' in data:
            if isinstance(data['cc'], basestring):
                # Supposed to be a list, fix it up for them.
                data['cc'] = [data['cc']]
            email_validator = validators.Email(not_empty=True)
            for addr in data['cc']:
                try:
                    email_validator.to_python(addr)
                except Invalid as e:
                    raise BadRequest400('Invalid email address %r in cc: %s'
                            % (addr, str(e)))
            new_addrs = set(data['cc'])
            existing_addrs = set(job.cc)
            for addr in new_addrs.difference(existing_addrs):
                record_activity(u'Cc', None, addr, action=u'Added')
            for addr in existing_addrs.difference(new_addrs):
                record_activity(u'Cc', addr, None, action=u'Removed')
            job.cc[:] = list(new_addrs)
    return jsonify(job.__json__())

@app.route('/jobs/<int:id>', methods=['DELETE'])
@auth_required
def delete_job(id):
    """
    Delete a job.

    :param id: Job's id
    """
    job = _get_job_by_id(id)
    if not job.can_delete(identity.current.user):
        raise Forbidden403('Cannot delete job')
    if not job.is_finished():
        raise BadRequest400('Cannot delete running job')
    try:
        job.soft_delete()
    except BeakerException as exc:
        raise BadRequest400(unicode(exc))
    return '', 204

@app.route('/jobs/<int:id>/activity/', methods=['GET'])
def get_job_activity(id):
    """
    Returns a JSON array of the historical activity records for a job.
    """
    # Not a "pageable JSON collection" like other activity APIs, because there 
    # is typically zero or a very small number of activity entries for any 
    # given job.
    # Also note this returns both JobActivity as well as RecipeSetActivity for 
    # the recipe sets in the job.
    job = _get_job_by_id(id)
    return jsonify({'entries': job.all_activity})

@app.route('/jobs/<int:id>/status', methods=['POST'])
@auth_required
def update_job_status(id):
    """
    Updates the status of a job. The request must be :mimetype:`application/json`.

    Currently the only allowed value for status is 'Cancelled', which has the 
    effect of cancelling all recipes in the job that have not finished yet.

    :param id: Job's id
    :jsonparam string status: The new status. Must be 'Cancelled'.
    :jsonparam string msg: A message describing the reason for updating the status.
    """
    job = _get_job_by_id(id)
    if not job.can_cancel(identity.current.user):
        raise Forbidden403('Cannot update job status')
    data = read_json_request(request)
    if 'status' not in data:
        raise BadRequest400('Missing status')
    status = TaskStatus.from_string(data['status'])
    msg = data.get('msg', None) or None
    if status != TaskStatus.cancelled:
        raise BadRequest400('Status must be "Cancelled"')
    with convert_internal_errors():
        job.record_activity(user=identity.current.user, service=u'HTTP',
                field=u'Status', action=u'Cancelled')
        job.cancel(msg=msg)
    return '', 204

@app.route('/jobs/+inventory', methods=['POST'])
@auth_required
def submit_inventory_job():
    """
    Submit a inventory job with the most suitable distro selected automatically.

    Returns a dictionary consisting of the job_id, recipe_id, status (recipe status) 
    and the job XML. If ``dryrun`` is set to ``True`` in the request, the first three 
    are set to ``None``.

    :jsonparam string fqdn: Fully-qualified domain name for the system.
    :jsonparam bool dryrun: If True, do not submit the job
    """
    if 'fqdn' not in request.json:
        raise BadRequest400('Missing the fqdn parameter')
    fqdn = request.json['fqdn']
    if 'dryrun' in request.json:
        dryrun = request.json['dryrun']
    else:
        dryrun = False
    try:
        system = System.by_fqdn(fqdn, identity.current.user)
    except NoResultFound:
        raise BadRequest400('System not found: %s' % fqdn)
    if system.find_current_hardware_scan_recipe():
        raise Conflict409('Hardware scanning already in progress')
    distro = system.distro_tree_for_inventory()
    if not distro:
        raise BadRequest400('Could not find a compatible distro for hardware scanning available to this system')
    job_details = {}
    job_details['system'] = system
    job_details['whiteboard'] = 'Update Inventory for %s' % fqdn
    with convert_internal_errors():
        job_xml = Job.inventory_system_job(distro, dryrun=dryrun, **job_details)
    r = {}
    if not dryrun:
        r = system.find_current_hardware_scan_recipe().__json__()
    else:
        r = {'recipe_id': None,
             'status': None,
             'job_id': None,
        }
    r['job_xml'] = job_xml
    r = jsonify(r)
    return r
# for sphinx
jobs = Jobs
