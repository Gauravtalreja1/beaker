from turbogears.database import session
from turbogears import controllers, expose, flash, widgets, validate, error_handler, validators, redirect, paginate, url
from turbogears import identity, redirect
from bkr.server.xmlrpccontroller import RPCRoot
from bkr.server.widgets import myPaginateDataGrid
from bkr.server.admin_page import AdminPage
from bkr.server.model import RetentionTag as Tag
from bkr.server.retention_tag_utility import RetentionTagUtility
from bkr.server.helpers import make_edit_link, make_link

import logging
log = logging.getLogger(__name__)

class RetentionTag(AdminPage):
    exposed = False

    tag = widgets.TextField(name='tag', label=_(u'Tag'))
    default = widgets.SingleSelectField(name='default', label=(u'Default'), options=[(0,'False'),(1,'True')])
    id = widgets.HiddenField(name='id') 

    tag_form = widgets.TableForm(
        'Retention Tag',
        fields = [tag, default,id],
        action = 'save_data',
        submit_text = _(u'Save'),
    )

    def __init__(self,*args,**kw):
        kw['search_url'] =  url("/retentiontag/by_tag")
        kw['search_name'] = 'tag'
        kw['widget_action'] = './admin'
        super(RetentionTag,self).__init__(*args,**kw)

        self.search_col = Tag.tag
        self.search_mapper = Tag 

    @identity.require(identity.in_group("admin"))
    @expose(template='bkr.server.templates.form')
    def new(self, **kw):
        return dict(
            form = self.tag_form,
            action = './save',
            options = {},
            value = kw,
        )


    @identity.require(identity.in_group("admin"))
    @expose()
    def save_edit(self, **kw):
        try:
            RetentionTagUtility.edit_default(**kw)
        except Exception, e:
            log.error('Error editing tag: %s and default: %s' % (kw.get('tag'), kw.get('default_')))
            flash(_(u"Problem editing tag %s" % kw.get('tag')))
            redirect("./admin")
        flash(_(u"OK"))
        redirect("./admin")

    @identity.require(identity.in_group("admin"))
    @expose()
    @validate(validators = { 'tag' : validators.UnicodeString(not_empty=True, max=20, strip=True) })
    @error_handler(new)
    def save(self, **kw):
        try:
            RetentionTagUtility.save_tag(**kw)
            session.flush()
        except Exception, e:
            log.error('Error inserting tag: %s and default: %s' % (kw.get('tag'), kw.get('default_')))
            flash(_(u"Problem saving tag %s" % kw.get('tag')))
        else:
            flash(_(u"OK"))
        redirect("./admin")
    
    @expose(format='json')
    def by_tag(self, input, *args, **kw):
        input = input.lower()
        search = Tag.list_by_tag(input)
        tags = [match.tag for match in search]
        return dict(matches=tags)

    @expose(template="bkr.server.templates.admin_grid")
    @identity.require(identity.in_group('admin'))
    @paginate('list', default_order='tag', limit=20)
    def admin(self, *args, **kw):
        tags = self.process_search(*args, **kw)
        alpha_nav_data = set([elem.tag[0].capitalize() for elem in tags])
        nav_bar = self._build_nav_bar(alpha_nav_data,'tag')
        template_data = self.tags(tags, identity.current.user, *args, **kw)
        template_data['alpha_nav_bar'] = nav_bar
        template_data['addable'] = True
        return template_data

    @identity.require(identity.in_group('admin'))
    @expose()
    def delete(self, id):
        tag = Tag.by_id(id)
        if not tag.can_delete(): # Trying to be funny...
            flash(u'%s is not applicable for deletion' % tag.tag)
            redirect('/retentiontag/admin')
        session.delete(tag)
        flash(u'Succesfully deleted %s' % tag.tag)
        redirect('/retentiontag/admin')

    @identity.require(identity.in_group("admin"))
    @expose(template='bkr.server.templates.tag_form')
    def edit(self, id, **kw):
        tag = Tag.by_id(id) 
        return dict(
            form = self.tag_form,
            action = './save_edit',
            options = {},
            value = tag,
            disabled_fields = ['tag']
        )

    @expose(template="bkr.server.templates.grid")
    @paginate('list', default_order='tag', limit=20)
    def index(self, *args, **kw):
        return self.tags()

    def tags(self, tags=None, user=None, *args, **kw):
        if tags is None:
            tags = Tag.get_all()

        def show_delete(x):
            if x.can_delete():
                return make_link(url='./delete/%s' % x.id, text='Delete')
            else:
                return None

        def show_tag(x):
            if x.is_default: #If we are the default, we can't change to not default
                return x.tag
            elif user and user.is_admin():
                return make_edit_link(x.tag,x.id)
            else:  #no perms to edit
                return x.tag

        my_fields = [myPaginateDataGrid.Column(name='tag', title='Tags', getter=lambda x: show_tag(x),options=dict(sortable=True)),
                     myPaginateDataGrid.Column(name='default', title='Default', getter=lambda x: x.default,options=dict(sortable=True)),
                     myPaginateDataGrid.Column(name='delete', title='Delete', getter=lambda x: show_delete(x))]
        tag_grid = myPaginateDataGrid(fields=my_fields)
        return_dict = dict(title='Tags',
                           grid = tag_grid,
                           object_count = tags.count(),
                           search_bar = None,
                           search_widget = self.search_widget_form,
                           list = tags)
        return return_dict
