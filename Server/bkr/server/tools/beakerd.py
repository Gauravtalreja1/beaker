#!/usr/bin/env python
# Beaker - 
#
# Copyright (C) 2008 bpeck@redhat.com
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

# -*- coding: utf-8 -*-

import sys
import os
import random
from bkr.server.bexceptions import BX, CobblerTaskFailedException
from bkr.server.model import *
from bkr.server.util import load_config, log_traceback
from bkr.server.recipetasks import RecipeTasks
from bkr.server.message_bus import ServerBeakerBus
from turbogears.database import session
from turbogears import config
from turbomail.control import interface
from xmlrpclib import ProtocolError

import socket
import exceptions
from datetime import datetime, timedelta
import time
import daemon
import atexit
import signal
from lockfile import pidlockfile
from daemon import pidfile
import threading

import logging

log = logging.getLogger("beakerd")
running = True
event = threading.Event()

from optparse import OptionParser

__version__ = '0.1'
__description__ = 'Beaker Scheduler'


def get_parser():
    usage = "usage: %prog [options]"
    parser = OptionParser(usage, description=__description__,
                          version=__version__)

    ## Defaults
    parser.set_defaults(daemonize=True, log_level=None)
    ## Actions
    parser.add_option("-f", "--foreground", default=False, action="store_true",
                      help="run in foreground (do not spawn a daemon)")
    parser.add_option("-p", "--pid-file",
                      help="specify a pid file")
    parser.add_option('-l', '--log-level', dest='log_level', metavar='LEVEL',
                      help='log level (ie. INFO, WARNING, ERROR, CRITICAL)')
    parser.add_option("-c", "--config", action="store", type="string",
                      dest="configfile", help="location of config file.")
    parser.add_option("-u", "--user", action="store", type="string",
                      dest="user_name", help="username of Admin account")

    return parser


def new_recipes(*args):
    recipes = Recipe.query.filter(Recipe.status == TaskStatus.new)
    if not recipes.count():
        return False
    log.debug("Entering new_recipes routine")
    for recipe_id, in recipes.values(Recipe.id):
        session.begin()
        try:
            recipe = Recipe.by_id(recipe_id)
            if recipe.distro_tree:
                recipe.systems = []

                # Do the query twice. 

                # First query verifies that the distro tree
                # exists in at least one lab that has a macthing system.
                systems = recipe.distro_tree.systems_filter(
                                            recipe.recipeset.job.owner,
                                            recipe.host_requires,
                                            only_in_lab=True)
                # Second query picksup all possible systems so that as 
                # trees appear in other labs those systems will be
                # available.
                all_systems = recipe.distro_tree.systems_filter(
                                            recipe.recipeset.job.owner,
                                            recipe.host_requires,
                                            only_in_lab=False)
                # based on above queries, condition on systems but add
                # all_systems.
                if systems.count():
                    for system in all_systems:
                        # Add matched systems to recipe.
                        recipe.systems.append(system)

                # If the recipe only matches one system then bump its priority.
                if len(recipe.systems) == 1:
                    try:
                        log.info("recipe ID %s matches one system, bumping priority" % recipe.id)
                        recipe.recipeset.priority = TaskPriority.by_index(
                                TaskPriority.index(recipe.recipeset.priority) + 1)
                    except IndexError:
                        # We may already be at the highest priority
                        pass
                if recipe.systems:
                    recipe.process()
                    log.info("recipe ID %s moved from New to Processed" % recipe.id)
                else:
                    log.info("recipe ID %s moved from New to Aborted" % recipe.id)
                    recipe.recipeset.abort(u'Recipe ID %s does not match any systems' % recipe.id)
            else:
                recipe.recipeset.abort(u'Recipe ID %s does not have a distro tree' % recipe.id)
            session.commit()
        except exceptions.Exception:
            session.rollback()
            log.exception("Failed to commit in new_recipes")
        session.close()
    log.debug("Exiting new_recipes routine")
    return True

def processed_recipesets(*args):
    recipesets = RecipeSet.query.filter(RecipeSet.status == TaskStatus.processed)
    if not recipesets.count():
        return False
    log.debug("Entering processed_recipes routine")
    for rs_id, in recipesets.values(RecipeSet.id):
        session.begin()
        try:
            recipeset = RecipeSet.by_id(rs_id)
            bad_l_controllers = set()
            # We only need to do this processing on multi-host recipes
            if len(recipeset.recipes) == 1:
                log.info("recipe ID %s moved from Processed to Queued" % recipeset.recipes[0].id)
                recipeset.recipes[0].queue()
            else:
                # Find all the lab controllers that this recipeset may run.
                rsl_controllers = set(LabController.query\
                                              .join(['systems',
                                                     'queued_recipes',
                                                     'recipeset'])\
                                              .filter(RecipeSet.id==recipeset.id).all())
    
                # Any lab controllers that are not associated to all recipes in the
                # recipe set must have those systems on that lab controller removed
                # from any recipes.  For multi-host all recipes must be schedulable
                # on one lab controller
                for recipe in recipeset.recipes:
                    rl_controllers = set(LabController.query\
                                               .join(['systems',
                                                      'queued_recipes'])\
                                               .filter(Recipe.id==recipe.id).all())
                    bad_l_controllers = bad_l_controllers.union(rl_controllers.difference(rsl_controllers))
        
                for l_controller in rsl_controllers:
                    enough_systems = False
                    for recipe in recipeset.recipes:
                        systems = recipe.dyn_systems.filter(
                                                  System.lab_controller==l_controller
                                                           ).all()
                        if len(systems) < len(recipeset.recipes):
                            break
                    else:
                        # There are enough choices We don't need to worry about dead
                        # locks
                        enough_systems = True
                    if not enough_systems:
                        log.debug("recipe: %s labController:%s entering not enough systems logic" % 
                                              (recipe.id, l_controller))
                        # Eliminate bad choices.
                        for recipe in recipeset.recipes_orderby(l_controller)[:]:
                            for tmprecipe in recipeset.recipes:
                                systemsa = set(recipe.dyn_systems.filter(
                                                  System.lab_controller==l_controller
                                                                        ).all())
                                systemsb = set(tmprecipe.dyn_systems.filter(
                                                  System.lab_controller==l_controller
                                                                           ).all())
        
                                if systemsa.difference(systemsb):
                                    for rem_system in systemsa.intersection(systemsb):
                                        if rem_system in recipe.systems:
                                            log.debug("recipe: %s labController:%s Removing system %s" % (recipe.id, l_controller, rem_system))
                                            recipe.systems.remove(rem_system)
                        for recipe in recipeset.recipes:
                            count = 0
                            systems = recipe.dyn_systems.filter(
                                              System.lab_controller==l_controller
                                                               ).all()
                            for tmprecipe in recipeset.recipes:
                                tmpsystems = tmprecipe.dyn_systems.filter(
                                                  System.lab_controller==l_controller
                                                                         ).all()
                                if recipe != tmprecipe and \
                                   systems == tmpsystems:
                                    count += 1
                            if len(systems) <= count:
                                # Remove all systems from this lc on this rs.
                                log.debug("recipe: %s labController:%s %s <= %s Removing lab" % (recipe.id, l_controller, len(systems), count))
                                bad_l_controllers = bad_l_controllers.union([l_controller])
        
                # Remove systems that are on bad lab controllers
                # This means one of the recipes can be fullfilled on a lab controller
                # but not the rest of the recipes in the recipeSet.
                # This could very well remove ALL systems from all recipes in this
                # recipeSet.  If that happens then the recipeSet cannot be scheduled
                # and will be aborted by the abort process.
                for recipe in recipeset.recipes:
                    for l_controller in bad_l_controllers:
                        systems = (recipe.dyn_systems.filter(
                                                  System.lab_controller==l_controller
                                                        ).all()
                                      )
                        log.debug("recipe: %s labController: %s Removing lab" % (recipe.id, l_controller))
                        for system in systems:
                            if system in recipe.systems:
                                log.debug("recipe: %s labController: %s Removing system %s" % (recipe.id, l_controller, system))
                                recipe.systems.remove(system)
                    if recipe.systems:
                        # Set status to Queued 
                        log.info("recipe: %s moved from Processed to Queued" % recipe.id)
                        recipe.queue()
                    else:
                        # Set status to Aborted 
                        log.info("recipe ID %s moved from Processed to Aborted" % recipe.id)
                        recipe.recipeset.abort(u'Recipe ID %s does not match any systems' % recipe.id)
                        
            session.commit()
        except exceptions.Exception:
            session.rollback()
            log.exception("Failed to commit in processed_recipes")
        session.close()
    log.debug("Exiting processed_recipes routine")
    return True

def dead_recipes(*args):
    recipes = Recipe.query\
                    .outerjoin(Recipe.distro_tree)\
                    .filter(
                         or_(
                         and_(Recipe.status==TaskStatus.queued,
                              not_(Recipe.systems.any()),
                             ),
                         and_(Recipe.status==TaskStatus.queued,
                              not_(DistroTree.lab_controller_assocs.any()),
                             ),
                            )
                           )

    if not recipes.count():
        return False
    log.debug("Entering dead_recipes routine")
    for recipe_id, in recipes.values(Recipe.id):
        session.begin()
        try:
            recipe = Recipe.by_id(recipe_id)
            if len(recipe.systems) == 0:
                msg = u"R:%s does not match any systems, aborting." % recipe.id
                log.info(msg)
                recipe.recipeset.abort(msg)
            if len(recipe.distro_tree.lab_controller_assocs) == 0:
                msg = u"R:%s does not have a valid distro tree, aborting." % recipe.id
                log.info(msg)
                recipe.recipeset.abort(msg)
            session.commit()
        except exceptions.Exception, e:
            session.rollback()
            log.exception("Failed to commit due to :%s" % e)
        session.close()
    log.debug("Exiting dead_recipes routine")
    return True

def queued_recipes(*args):
    recipes = Recipe.query\
                    .join(Recipe.recipeset, RecipeSet.job)\
                    .join(Recipe.systems)\
                    .join(Recipe.distro_tree)\
                    .join(DistroTree.lab_controller_assocs,
                        (LabController, and_(
                            LabControllerDistroTree.lab_controller_id == LabController.id,
                            System.lab_controller_id == LabController.id)))\
                    .filter(
                         and_(Recipe.status==TaskStatus.queued,
                              System.user==None,
                              System.status==SystemStatus.automated,
                              LabController.disabled==False,
                              or_(
                                  RecipeSet.lab_controller==None,
                                  RecipeSet.lab_controller_id==System.lab_controller_id,
                                 ),
                              or_(
                                  System.loan_id==None,
                                  System.loan_id==Job.owner_id,
                                 ),
                             )
                           )
    # Order recipes by priority.
    # FIXME Add secondary order by number of matched systems.
    if True:
        recipes = recipes.order_by(RecipeSet.priority.desc())
    # order recipes by id
    recipes = recipes.order_by(Recipe.id)
    if not recipes.count():
        return False
    log.debug("Entering queued_recipes routine")
    for recipe_id, in recipes.values(Recipe.id.distinct()):
        session.begin()
        try:
            recipe = Recipe.by_id(recipe_id)
            systems = recipe.dyn_systems\
                       .join(System.lab_controller)\
                       .filter(and_(System.user==None,
                                  LabController._distro_trees.any(
                                    LabControllerDistroTree.distro_tree == recipe.distro_tree),
                                  LabController.disabled==False,
                                  System.status==SystemStatus.automated,
                                  or_(
                                      System.loan_id==None,
                                      System.loan_id==recipe.recipeset.job.owner_id,
                                     ),
                                   )
                              )
            # Order systems by owner, then Group, finally shared for everyone.
            # FIXME Make this configurable, so that a user can specify their scheduling
            # Implemented order, still need to do pool
            # preference from the job.
            # <recipe>
            #  <autopick order='sequence|random'>
            #   <pool>owner</pool>
            #   <pool>groups</pool>
            #   <pool>public</pool>
            #  </autopick>
            # </recipe>
            user = recipe.recipeset.job.owner
            if True: #FIXME if pools are defined add them here in the order requested.
                systems = systems.order_by(case([(System.owner==user, 1),
                          (and_(System.owner!=user, System.group_assocs != None), 2)],
                              else_=3))
            if recipe.recipeset.lab_controller:
                # First recipe of a recipeSet determines the lab_controller
                systems = systems.filter(
                             System.lab_controller==recipe.recipeset.lab_controller
                                      )
            if recipe.autopick_random:
                try:
                    system = systems[random.randrange(0,systems.count())]
                except (IndexError, ValueError):
                    system = None
            else:
                system = systems.first()
            if system:
                log.debug("System : %s is available for Recipe %s" % (system, recipe.id))
                # Check to see if user still has proper permissions to use system
                # Remember the mapping of available systems could have happend hours or even
                # days ago and groups or loans could have been put in place since.
                if not System.free(user).filter(System.id == system.id).first():
                    log.debug("System : %s recipe: %s no longer has access. removing" % (system, 
                                                                                         recipe.id))
                    recipe.systems.remove(system)
                else:
                    recipe.schedule()
                    recipe.createRepo()
                    system.reserve(service=u'Scheduler', user=recipe.recipeset.job.owner,
                            reservation_type=u'recipe', recipe=recipe)
                    recipe.system = system
                    recipe.recipeset.lab_controller = system.lab_controller
                    recipe.systems = []
                    # Create the watchdog without an Expire time.
                    log.debug("Created watchdog for recipe id: %s and system: %s" % (recipe.id, system))
                    recipe.watchdog = Watchdog(system=recipe.system)
                    # If we start ok, we need to send event active watchdog event
                    if config.get('beaker.qpid_enabled'):
                        bb = ServerBeakerBus()
                        bb.send_action('watchdog_notify', 'active',
                            [{'recipe_id' : recipe.id, 
                            'system' : recipe.watchdog.system.fqdn}], 
                            recipe.watchdog.system.lab_controller.fqdn)
                    log.info("recipe ID %s moved from Queued to Scheduled" % recipe.id)
            session.commit()
        except exceptions.Exception:
            session.rollback()
            log.exception("Failed to commit in queued_recipes")
        session.close()
    log.debug("Exiting queued_recipes routine")
    return True

def scheduled_recipes(*args):
    """
    if All recipes in a recipeSet are in Scheduled state then move them to
     Running.
    """
    recipesets = RecipeSet.query.filter(not_(RecipeSet.recipes.any(
            Recipe.status != TaskStatus.scheduled)))
    if not recipesets.count():
        return False
    log.debug("Entering scheduled_recipes routine")
    for rs_id, in recipesets.values(RecipeSet.id):
        log.info("scheduled_recipes: RS:%s" % rs_id)
        session.begin()
        try:
            recipeset = RecipeSet.by_id(rs_id)
            # Go through each recipe in the recipeSet
            for recipe in recipeset.recipes:
                # If one of the recipes gets aborted then don't try and run
                if recipe.status != TaskStatus.scheduled:
                    break
                recipe.waiting()

                # Go Through each recipe and find out everyone's role.
                for peer in recipe.recipeset.recipes:
                    recipe.roles[peer.role].append(peer.system)

                # Go Through each task and find out the roles of everyone else
                for i, task in enumerate(recipe.tasks):
                    for peer in recipe.recipeset.recipes:
                        # Roles are only shared amongst like recipe types
                        if type(recipe) == type(peer):
                            try:
                                task.roles[peer.tasks[i].role].append(peer.system)
                            except IndexError:
                                # We have uneven tasks
                                pass

                repo_fail = []
                if not recipe.harness_repo():
                    repo_fail.append(u'harness')
                if not recipe.task_repo():
                    repo_fail.append(u'task')

                if repo_fail:
                    repo_fail_msg ='Failed to find repo for %s' % ','.join(repo_fail)
                    log.error(repo_fail_msg)
                    recipe.recipeset.abort(repo_fail_msg)
                    break

                try:
                    recipe.provision()
                    recipe.system.activity.append(
                         SystemActivity(recipe.recipeset.job.owner, 
                                        u'Scheduler',
                                        u'Provision',
                                        u'Distro Tree',
                                        u'',
                                        unicode(recipe.distro_tree)))
                except Exception, e:
                    log.exception("Failed to provision recipeid %s", recipe.id)
                    recipe.recipeset.abort(u"Failed to provision recipeid %s, %s" % 
                                                                             (
                                                                             recipe.id,
                                                                            e))
       
            session.commit()
        except exceptions.Exception:
            session.rollback()
            log.exception("Failed to commit in scheduled_recipes")
        session.close()
    log.debug("Exiting scheduled_recipes routine")
    return True

def recipe_count_metrics():
    query = Recipe.query.group_by(Recipe.status)\
            .having(Recipe.status.in_([s for s in TaskStatus if not s.finished]))\
            .values(Recipe.status, func.count(Recipe.id))
    for status, count in query:
        metrics.measure('gauges.recipes_%s' % status.name, count)

# These functions are run in separate threads, so we want to log any uncaught 
# exceptions instead of letting them be written to stderr and lost to the ether

@log_traceback(log)
def new_recipes_loop(*args, **kwargs):
    while running:
        if not new_recipes():
            event.wait()
    log.debug("new recipes thread exiting")

@log_traceback(log)
def processed_recipesets_loop(*args, **kwargs):
    while running:
        if not processed_recipesets():
            event.wait()
    log.debug("processed recipesets thread exiting")

@log_traceback(log)
def metrics_loop(*args, **kwargs):
    while running:
        try:
            start = time.time()
            log.debug('Sending recipe count metrics')
            recipe_count_metrics()
        except Exception:
            log.exception('Exception in metrics loop')
        time.sleep(max(10.0 + start - time.time(), 5.0))

@log_traceback(log)
def main_recipes_loop(*args, **kwargs):
    while running:
        dead_recipes()
        queued = queued_recipes()
        scheduled = scheduled_recipes()
        if not queued and not scheduled:
            event.wait()
    log.debug("main recipes thread exiting")

def schedule():
    global running
    reload_config()

    if config.get('beaker.qpid_enabled') is True: 
       bb = ServerBeakerBus()
       bb.run()

    if config.get('carbon.address'):
        log.debug('starting metrics thread')
        metrics_thread = threading.Thread(target=metrics_loop, name='metrics')
        metrics_thread.daemon = True
        metrics_thread.start()

    beakerd_threads = set(["new_recipes", "processed_recipesets",\
                           "main_recipes"])

    log.debug("starting new recipes thread")
    new_recipes_thread = threading.Thread(target=new_recipes_loop,
                                          name="new_recipes")
    new_recipes_thread.daemon = True
    new_recipes_thread.start()

    log.debug("starting processed_recipes thread")
    processed_recipesets_thread = threading.Thread(target=processed_recipesets_loop,
                                                   name="processed_recipesets")
    processed_recipesets_thread.daemon = True
    processed_recipesets_thread.start()

    log.debug("starting main recipes thread")
    main_recipes_thread = threading.Thread(target=main_recipes_loop,
                                           name="main_recipes")
    main_recipes_thread.daemon = True
    main_recipes_thread.start()

    try:
        while True:
            time.sleep(20)
            running_threads = set([t.name for t in threading.enumerate()])
            if not running_threads.issuperset(beakerd_threads):
                log.critical("a thread has died, shutting down")
                rc = 1
                running = False
                event.set()
                break
            event.set()
            event.clear()
    except (SystemExit, KeyboardInterrupt):
       log.info("shutting down")
       running = False
       event.set()
       rc = 0

    new_recipes_thread.join(10)
    processed_recipesets_thread.join(10)
    main_recipes_thread.join(10)

    sys.exit(rc)

@atexit.register
def atexit():
    interface.stop()

def sighup_handler(signal, frame):
    log.info("received SIGHUP, reloading")
    reload_config()
    log.info("configuration reloaded")

def sigterm_handler(signal, frame):
    raise SystemExit("received SIGTERM")

def reload_config():
    for (_, logger) in logging.root.manager.loggerDict.items():
        if hasattr(logger, 'handlers'):
            for handler in logger.handlers:
                logger.removeHandler(handler)
    for handler in logging._handlerList[:]:
        handler.flush()
        handler.close()
    if interface.running:
        interface.stop()

    load_config(opts.configfile)
    config.update({'identity.krb_auth_qpid_principal':
                       config.get('identity.krb_auth_beakerd_principal'),
                   'identity.krb_auth_qpid_keytab':
                       config.get('identity.krb_auth_beakerd_keytab')})
    interface.start(config)

def main():
    global opts
    parser = get_parser()
    opts, args = parser.parse_args()

    # First look on the command line for a desired config file,
    # if it's not on the command line, then look for 'setup.py'
    # in the current directory. If there, load configuration
    # from a file called 'dev.cfg'. If it's not there, the project
    # is probably installed and we'll look first for a file called
    # 'prod.cfg' in the current directory and then for a default
    # config file called 'default.cfg' packaged in the egg.
    load_config(opts.configfile)

    if not opts.foreground:
        log.debug("Launching beakerd daemon")
        pid_file = opts.pid_file
        if pid_file is None:
            pid_file = config.get("PID_FILE", "/var/run/beaker/beakerd.pid")
        d = daemon.DaemonContext(pidfile=pidfile.TimeoutPIDLockFile(pid_file, acquire_timeout=0),
                                 signal_map={signal.SIGHUP: sighup_handler,
                                             signal.SIGTERM: sigterm_handler})
        util_logger = logging.getLogger('bkr.server.util')
        util_logger.disabled = True
        for (_, logger) in logging.root.manager.loggerDict.items():
            if hasattr(logger, 'handlers'):
                for handler in logger.handlers:
                    logger.removeHandler(handler)
        for handler in logging._handlerList[:]:
            handler.flush()
            handler.close()
        try:
            d.open()
        except pidlockfile.AlreadyLocked:
            reload_config() # reopen logfiles
            log.fatal("could not acquire lock on %s, exiting" % pid_file)
            sys.stderr.write("could not acquire lock on %s" % pid_file)
            sys.exit(1)

    schedule()

if __name__ == "__main__":
    main()
