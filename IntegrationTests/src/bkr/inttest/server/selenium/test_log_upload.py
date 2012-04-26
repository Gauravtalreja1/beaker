
import base64
import hashlib
from bkr.server.model import session
from bkr.inttest import data_setup
from bkr.inttest.server.selenium import XmlRpcTestCase

class LogUploadXmlRpcTest(XmlRpcTestCase):

    def setUp(self):
        with session.begin():
            self.lc = data_setup.create_labcontroller()
            self.lc.user.password = u'logmein'
            job = data_setup.create_job()
            self.recipe = job.recipesets[0].recipes[0]
            session.flush()
            self.recipe.logs = []
        self.server = self.get_server()

    def test_register_recipe_log(self):
        self.server.auth.login_password(self.lc.user.user_name, 'logmein')
        self.server.recipes.register_file('http://myserver/log.txt',
                self.recipe.id, '/', 'log.txt', '')
        with session.begin():
            session.refresh(self.recipe)
            self.assertEquals(len(self.recipe.logs), 1, self.recipe.logs)
            self.assertEquals(self.recipe.logs[0].path, u'/')
            self.assertEquals(self.recipe.logs[0].filename, u'log.txt')
            self.assertEquals(self.recipe.logs[0].server, u'http://myserver/log.txt')
        # Register it again with a different URL
        self.server.recipes.register_file('http://elsewhere/log.txt',
                self.recipe.id, '/', 'log.txt', '')
        with session.begin():
            session.refresh(self.recipe)
            self.assertEquals(len(self.recipe.logs), 1, self.recipe.logs)
            self.assertEquals(self.recipe.logs[0].path, u'/')
            self.assertEquals(self.recipe.logs[0].filename, u'log.txt')
            self.assertEquals(self.recipe.logs[0].server, u'http://elsewhere/log.txt')

    def test_upload_recipe_log(self):
        chunk = '0123456789'
        chunk_b64 = base64.b64encode(chunk)
        chunk_md5 = hashlib.md5(chunk).hexdigest()
        self.server.auth.login_password(self.lc.user.user_name, 'logmein')
        self.server.recipes.upload_file(self.recipe.id, '/', 'log.txt',
                10, chunk_md5, 0, chunk_b64)
        with session.begin():
            session.refresh(self.recipe)
            self.assertEquals(len(self.recipe.logs), 1, self.recipe.logs)
            self.assertEquals(self.recipe.logs[0].path, u'/')
            self.assertEquals(self.recipe.logs[0].filename, u'log.txt')
        self.server.recipes.upload_file(self.recipe.id, '/', 'log.txt',
                20, chunk_md5, 10, chunk_b64)
        with session.begin():
            session.refresh(self.recipe)
            self.assertEquals(len(self.recipe.logs), 1, self.recipe.logs)
            self.assertEquals(self.recipe.logs[0].path, u'/')
            self.assertEquals(self.recipe.logs[0].filename, u'log.txt')
