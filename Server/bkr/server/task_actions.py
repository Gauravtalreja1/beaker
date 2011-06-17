
"""
XML-RPC methods in the :mod:`taskactions` namespace can be applied to a running 
job or any of its constituent parts (recipe sets, recipes, tasks, and task 
results). For methods related to Beaker's task library, see the 
:ref:`task-library` section.

These methods accept a *taskid* argument, which must be a string of the form 
*type*:*id*, for example ``'RS:4321'``. The server recognises the following 
values for *type*:

* J: Job
* RS: Recipe set
* R: Recipe
* T: Task within a recipe
* TR: Result within a task
"""

from turbogears.database import session
from turbogears import expose
from bkr.server.model import *
from bkr.server.bexceptions import BX
from bkr.server.xmlrpccontroller import RPCRoot
import cherrypy

__all__ = ['TaskActions']

class TaskActions(RPCRoot):
    # For XMLRPC methods in this class.
    exposed = True
    unstoppable_task_types = [Recipe, RecipeTaskResult]

    task_types = dict(J  = Job,
                      RS = RecipeSet,
                      R  = Recipe,
                      T  = RecipeTask,
                      TR = RecipeTaskResult)

    stoppable_task_types = dict([(rep, obj) for rep,obj in task_types.iteritems() if obj not in unstoppable_task_types])

    @cherrypy.expose
    def task_info(self, taskid,flat=True):
        """
        Returns an XML-RPC structure (dict) describing the current state of the 
        given job component.

        :param taskid: see above
        :type taskid: string
        """
        return TaskBase.get_by_t_id(taskid).task_info()

    @cherrypy.expose
    def to_xml(self, taskid,clone=False,from_job=True):
        """
        Returns an XML representation of the given job component, including its 
        current state.

        :param taskid: see above
        :type taskid: string
        """
        task_type, task_id = taskid.split(":")
        if task_type.upper() in self.task_types.keys():
            try:
                task = self.task_types[task_type.upper()].by_id(task_id)
            except InvalidRequestError, e:
                raise BX(_("Invalid %s %s" % (task_type, task_id)))
        return task.to_xml(clone,from_job).toxml()

    @cherrypy.expose
    def stop(self, taskid, stop_type, msg):
        """
        Cancels the given job. Note that when cancelling some part of a job 
        (for example, by passing *taskid* starting with ``R:`` to indicate 
        a particular recipe within a job) the entire job is cancelled.

        :param taskid: see above
        :type taskid: string
        :param stop_type: must be ``'cancel'`` (other values are reserved for 
            Beaker's internal use)
        :type stop_type: string
        :param msg: reason for cancelling
        :type msg: string
        """
        task_type, task_id = taskid.split(":")
        if task_type.upper() in self.stoppable_task_types.keys():
            try:
                task = self.stoppable_task_types[task_type.upper()].by_id(task_id)
            except InvalidRequestError, e:
                raise BX(_("Invalid %s %s" % (task_type, task_id)))
        else:
            raise BX(_("Task type %s is not stoppable" % (task_type)))
        if stop_type not in task.stop_types:
            raise BX(_('Invalid stop_type: %s, must be one of %s' %
                             (stop_type, task.stop_types)))
        kwargs = dict(msg = msg)
        return getattr(task,stop_type)(**kwargs)

# for sphinx
taskactions = TaskActions
