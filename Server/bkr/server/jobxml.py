#!/usr/bin/python

# Logan - Logan is the scheduling piece of the Beaker project
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

import xmltramp
import os
import sys

class ElementWrapper(object):
    @classmethod
    def get_subclass(cls, element):
        #print element
        
        name = element._name

        #print name
        #print type(name)

        #print subclassDict

        if name in subclassDict:
            return subclassDict[name]
        return UnknownElement
    
    def __init__(self, wrappedEl):
        self.wrappedEl = wrappedEl

    def __repr__(self):
        return '%s("%s")' % (self.__class__, repr(self.wrappedEl))

    def __iter__(self):
        for child in self.wrappedEl:
            if isinstance(child, xmltramp.Element):
                yield ElementWrapper.get_subclass(child)(child)
            else:
                yield child

    def __getitem__(self, n):
        child = self.wrappedEl[n]
        if isinstance(child, xmltramp.Element):
            return ElementWrapper.get_subclass(child)(child)
        else:
            return child
        

    def recurse(self, visitor):
        visitor.visit(self)
        for child in self:
            child.recurse(visitor)

    def get_text(self):
        # Simple API for extracting textual content below this node, stripping
        # out any markup
        #print 'get_text: %s' % self
        result = ''
        for child in self:
            if isinstance(child, ElementWrapper):
                # Recurse:
                result += child.get_text()
            else:
                #print child
                result += child

        return result

    def get_xml_attr(self, attr, typeCast, defaultValue):
        if attr in self.wrappedEl._attrs:
            return typeCast(self.wrappedEl(attr))
        else:
            return defaultValue

class UnknownElement(ElementWrapper):
    pass

class XmlJob(ElementWrapper):
    def iter_recipeSets(self):
        for recipeSet in self.wrappedEl['recipeSet':]:
            yield XmlRecipeSet(recipeSet)

    def __getattr__(self, attrname):
        try:
            return self.wrappedEl[attrname]
        except: 
            raise AttributeError, attrname

class XmlRecipeSet(ElementWrapper):
    def iter_recipes(self):
        for recipe in self.wrappedEl['recipe':]:
            yield XmlRecipeMachine(recipe)

class XmlRecipe(ElementWrapper):
    def iter_tasks(self, filter=None):
        for task in self.wrappedEl['task':]:
            if filter:
                if XmlTask(task).status in filter:
                    yield XmlTask(task)
            else:
                yield XmlTask(task)

    def packages(self):
        for packages in self.wrappedEl['packages':]:
            for package in packages['package':]:
                yield XmlPackage(package)

    def installPackages(self):
        for installpackage in self.wrappedEl['installPackage':]:
            yield installpackage

    def iter_repos(self):
        for repos in self.wrappedEl['repos':]:
            for repo in repos['repo':]:
                yield XmlRepo(repo)

    def distroRequires(self, *args):
        return self.wrappedEl['distroRequires'].__repr__(True)

    def hostRequires(self, *args):
        return self.wrappedEl['hostRequires'].__repr__(True)

    def __getattr__(self, attrname):
        if attrname == 'arch':
            return self.get_xml_attr('arch', unicode, None)
        elif attrname == 'id': 
            return self.get_xml_attr('id', int, 0)
        elif attrname == 'recipe_set_id': 
            return self.get_xml_attr('recipe_set_id', int, 0)
        elif attrname == 'job_id': 
            return self.get_xml_attr('job_id', int, 0)
        elif attrname == 'distro': 
            return self.get_xml_attr('distro', unicode, None)
        elif attrname == 'family': 
            return self.get_xml_attr('family', unicode, None)
        elif attrname == 'variant': 
            return self.get_xml_attr('variant', unicode, None)
        elif attrname == 'machine': 
            return self.get_xml_attr('machine', unicode, None)
        elif attrname == 'status': 
            return self.get_xml_attr('status', unicode, None)
        elif attrname == 'result': 
            return self.get_xml_attr('result', unicode, None)
        elif attrname == 'ks_meta':
            return self.get_xml_attr('ks_meta', unicode, None)
        elif attrname == 'kernel_options':
            return self.get_xml_attr('kernel_options', unicode, None)
        elif attrname == 'kernel_options_post':
            return self.get_xml_attr('kernel_options_post', unicode, None)
        elif attrname == 'whiteboard':
            return self.get_xml_attr('whiteboard', unicode, None)
        elif attrname == 'kickstart':
            try:
                return ''.join([t for t in self.wrappedEl['kickstart']])
            except: 
                return None
        elif attrname == 'role':
            return self.get_xml_attr('role', unicode, u'None')
        else: raise AttributeError, attrname

class XmlRecipeMachine(XmlRecipe):
    def iter_guests(self):
        for guest in self.wrappedEl['guestrecipe':]:
            yield XmlRecipeGuest(guest)

class XmlRecipeGuest(XmlRecipe):
    def __getattr__(self, attrname):
        if attrname == 'guestargs':
            return self.get_xml_attr('guestargs', unicode, None)
        elif attrname == 'guestname': 
            return self.get_xml_attr('guestname', unicode, None)
	else: return XmlRecipe.__getattr__(self,attrname)

class XmlTask(ElementWrapper):
    def iter_params(self):
        for params in self.wrappedEl['params':]:
            for param in params['param':]:
                yield XmlParam(param)

    def __getattr__(self, attrname):
        if attrname == 'role':
            return self.get_xml_attr('role', unicode, u'None')
        elif attrname == 'id': 
            return self.get_xml_attr('id', int, 0)
        elif attrname == 'name': 
            return self.get_xml_attr('name', unicode, u'None')
        elif attrname == 'avg_time': 
            return self.get_xml_attr('avg_time', int, 0)
        elif attrname == 'status': 
            return self.get_xml_attr('status', unicode, u'None')
        elif attrname == 'result': 
            return self.get_xml_attr('result', unicode, u'None')
        elif attrname == 'rpm': 
            return XmlRpm(self.wrappedEl['rpm'])
        else: raise AttributeError, attrname


class XmlPackage(ElementWrapper):
    def __getattr__(self, attrname):
        if attrname == 'name':
            return self.get_xml_attr('name', unicode, u'None')
        else: raise AttributeError, attrname

class XmlRepo(ElementWrapper):
    def __getattr__(self, attrname):
        if attrname == 'name':
            return self.get_xml_attr('name', unicode, u'None')
        elif attrname == 'url': 
            return self.get_xml_attr('url', unicode, u'None')
        else: raise AttributeError, attrname

class XmlParam(ElementWrapper):
    def __getattr__(self, attrname):
        if attrname == 'name':
            return self.get_xml_attr('name', unicode, u'None')
        elif attrname == 'value': 
            return self.get_xml_attr('value', unicode, u'None')
        else: raise AttributeError, attrname

class XmlRpm(ElementWrapper):
    def __getattr__(self, attrname):
        if attrname == 'name':
            return self.get_xml_attr('name', unicode, u'None')
        else: raise AttributeError, attrname

subclassDict = {
    'job'         : XmlJob,
    'recipeSet'   : XmlRecipeSet,
    'recipe'      : XmlRecipe,
    'guestrecipe' : XmlRecipe,
    'task'        : XmlTask,
    }

if __name__=='__main__':
    file = sys.argv[1]
    FH = open(file,"r")
    xml = FH.read()
    FH.close()

    myJob = xmltramp.parse(xml)
    job   = XmlJob(myJob)

    print job.whiteboard
    for recipeSet in job.iter_recipeSets():
        for recipe in recipeSet.iter_recipes():
            for xmlpackage in recipe.packages():
                print xmlpackage.name
            print recipe.hostRequires()
            for guest in recipe.iter_guests():
                print guest.guestargs
                for task in guest.iter_tasks():
                    for params in task.iter_params():
                        print "%s = %s" % (params.name, params.value)
                    print "%s %s" % (task.role, task.name)
            for task in recipe.iter_tasks():
                for params in task.iter_params():
                    print "%s = %s" % (params.name, params.value)
                print "%s %s" % (task.role, task.name)
