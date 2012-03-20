from turbogears import expose,paginate
from sqlalchemy.orm import contains_eager, joinedload_all
from bkr.server.xmlrpccontroller import RPCRoot
from bkr.server.model import Watchdog, Recipe, RecipeSet, Job, System, RecipeTask
from bkr.server.widgets import myPaginateDataGrid

import logging
log = logging.getLogger(__name__)

class Watchdogs(RPCRoot):

    @expose('bkr.server.templates.grid')
    @paginate('list', limit=50, max_limit=None)
    def index(self, *args, **kw):
        query = Watchdog.by_status(status=u'active')\
                .join(Watchdog.recipe, Recipe.recipeset, RecipeSet.job)\
                .order_by(Job.id)\
                .options(
                    joinedload_all(Watchdog.recipe, Recipe.recipeset, RecipeSet.job),
                    joinedload_all(Watchdog.system, System.lab_controller),
                    joinedload_all(Watchdog.recipetask, RecipeTask.task))

        col = myPaginateDataGrid.Column
        fields = [col(name='job_id', getter=lambda x: x.recipe.recipeset.job.link, title="Job ID"),
                  col(name='system_name', getter=lambda x: x.system.link, title="System"),
                  col(name='lab_controller', getter=lambda x: x.system.lab_controller, title="Lab Controller"),
                  col(name='task_name', getter=lambda x: x.recipetask.link, title="Task Name"),
                  col(name='kill_time', getter=lambda x: x.kill_time,
                      title="Kill Time", options=dict(datetime=True))]

        watchdog_grid = myPaginateDataGrid(fields=fields)
        return dict(title="Watchdogs",
                grid=watchdog_grid,
                search_bar=None,
                object_count=query.count(),
                list=query)

