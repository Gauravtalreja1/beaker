import sys
import time
import unittest
import email
from turbogears.database import session
from bkr.server.installopts import InstallOptions
from bkr.server.model import System, SystemStatus, SystemActivity, TaskStatus, \
        SystemType, Job, JobCc, Key, Key_Value_Int, Key_Value_String, \
        Cpu, Numa, Provision, job_cc_table, Arch, DistroTree, \
        LabControllerDistroTree, TaskType, TaskPackage, Device, DeviceClass, \
        GuestRecipe
from bkr.inttest import data_setup
from nose.plugins.skip import SkipTest

class SchemaSanityTest(unittest.TestCase):

    def test_all_tables_use_innodb(self):
        engine = session.get_bind(System.mapper)
        if engine.url.drivername != 'mysql':
            raise SkipTest('not using MySQL')
        for table in engine.table_names():
            self.assertEquals(engine.scalar(
                    'SELECT engine FROM information_schema.tables '
                    'WHERE table_schema = DATABASE() AND table_name = %s',
                    table), 'InnoDB')

class TestSystem(unittest.TestCase):

    def setUp(self):
        session.begin()

    def tearDown(self):
        session.commit()
        session.close()

    def test_create_system_params(self):
        owner = data_setup.create_user()
        new_system = System(fqdn=u'test_fqdn', contact=u'test@email.com',
                            location=u'Brisbane', model=u'Proliant', serial=u'4534534',
                            vendor=u'Dell', type=SystemType.machine,
                            status=SystemStatus.automated,
                            owner=owner)
        session.flush()
        self.assertEqual(new_system.fqdn, 'test_fqdn')
        self.assertEqual(new_system.contact, 'test@email.com')
        self.assertEqual(new_system.location, 'Brisbane')
        self.assertEqual(new_system.model, 'Proliant')
        self.assertEqual(new_system.serial, '4534534')
        self.assertEqual(new_system.vendor, 'Dell')
        self.assertEqual(new_system.owner, owner)
    
    def test_add_user_to_system(self): 
        user = data_setup.create_user()
        system = data_setup.create_system()
        system.user = user
        session.flush()
        self.assertEquals(system.user, user)

    def test_remove_user_from_system(self):
        user = data_setup.create_user()
        system = data_setup.create_system()
        system.user = user
        system.user = None
        session.flush()
        self.assert_(system.user is None)

    def test_install_options_override(self):
        distro_tree = data_setup.create_distro_tree()
        system = data_setup.create_system()
        system.provisions[distro_tree.arch] = Provision(arch=distro_tree.arch,
                kernel_options='console=ttyS0 ksdevice=eth0 vnc')
        opts = system.install_options(distro_tree).combined_with(
                InstallOptions.from_strings('', u'ksdevice=eth1 !vnc', ''))
        # ksdevice should be overriden but console should be inherited
        # noverifyssl comes from server-test.cfg
        # vnc should be removed
        self.assertEqual(opts.kernel_options,
                dict(console='ttyS0', ksdevice='eth1', noverifyssl=None))

    def test_mark_broken_updates_history(self):
        system = data_setup.create_system(status = SystemStatus.automated)
        system.mark_broken(reason = "Attacked by cyborgs")
        session.flush()
        system_activity = system.dyn_activity.filter(SystemActivity.field_name == u'Status').first()
        self.assertEqual(system_activity.old_value, u'Automated')
        self.assertEqual(system_activity.new_value, u'Broken')

class TestSystemKeyValue(unittest.TestCase):

    def setUp(self):
        session.begin()

    def tearDown(self):
        session.commit()

    def test_removing_key_type_cascades_to_key_value(self):
        # https://bugzilla.redhat.com/show_bug.cgi?id=647566
        string_key_type = Key(u'COLOUR', numeric=False)
        int_key_type = Key(u'FAIRIES', numeric=True)
        system = data_setup.create_system()
        system.key_values_string.append(
                Key_Value_String(string_key_type, u'pretty pink'))
        system.key_values_int.append(Key_Value_Int(int_key_type, 9000))
        session.flush()

        session.delete(string_key_type)
        session.delete(int_key_type)
        session.flush()

        session.expunge_all()
        reloaded_system = System.query.get(system.id)
        self.assertEqual(reloaded_system.key_values_string, [])
        self.assertEqual(reloaded_system.key_values_int, [])

class TestBrokenSystemDetection(unittest.TestCase):

    # https://bugzilla.redhat.com/show_bug.cgi?id=637260
    # The 1-second sleeps here are so that the various timestamps
    # don't end up within the same second

    def setUp(self):
        session.begin()
        self.system = data_setup.create_system()
        self.system.status = SystemStatus.automated
        data_setup.create_completed_job(system=self.system)
        session.flush()
        time.sleep(1)

    def tearDown(self):
        session.commit()

    def abort_recipe(self, distro_tree=None):
        if distro_tree is None:
            distro_tree = data_setup.create_distro_tree(distro_tags=[u'RELEASED'])
        recipe = data_setup.create_recipe(distro_tree=distro_tree)
        data_setup.create_job_for_recipes([recipe])
        recipe.system = self.system
        recipe.tasks[0].status = TaskStatus.running
        recipe.update_status()
        session.flush()
        recipe.abort()

    def test_multiple_suspicious_aborts_triggers_broken_system(self):
        # first aborted recipe shouldn't trigger it
        self.abort_recipe()
        self.assertNotEqual(self.system.status, SystemStatus.broken)
        # another recipe with a different stable distro *should* trigger it
        self.abort_recipe()
        self.assertEqual(self.system.status, SystemStatus.broken)

    def test_status_change_is_respected(self):
        # two aborted recipes should trigger it...
        self.abort_recipe()
        self.abort_recipe()
        self.assertEqual(self.system.status, SystemStatus.broken)
        # then the owner comes along and marks it as fixed...
        self.system.status = SystemStatus.automated
        self.system.activity.append(SystemActivity(service=u'WEBUI',
                action=u'Changed', field_name=u'Status',
                old_value=u'Broken',
                new_value=unicode(self.system.status)))
        session.flush()
        time.sleep(1)
        # another recipe aborts...
        self.abort_recipe()
        self.assertNotEqual(self.system.status, SystemStatus.broken) # not broken! yet
        self.abort_recipe()
        self.assertEqual(self.system.status, SystemStatus.broken) # now it is

    def test_counts_distinct_stable_distros(self):
        first_distro_tree = data_setup.create_distro_tree(distro_tags=[u'RELEASED'])
        # two aborted recipes for the same distro shouldn't trigger it
        self.abort_recipe(distro_tree=first_distro_tree)
        self.abort_recipe(distro_tree=first_distro_tree)
        self.assertNotEqual(self.system.status, SystemStatus.broken)
        # .. but a different distro should
        self.abort_recipe()
        self.assertEqual(self.system.status, SystemStatus.broken)

    def test_updates_modified_date(self):
        orig_date_modified = self.system.date_modified
        self.abort_recipe()
        self.abort_recipe()
        self.assertEqual(self.system.status, SystemStatus.broken)
        self.assert_(self.system.date_modified > orig_date_modified)

class TestJob(unittest.TestCase):

    def setUp(self):
        session.begin()

    def tearDown(self):
        session.commit()

    def test_cc_property(self):
        job = data_setup.create_job()
        session.flush()
        session.execute(job_cc_table.insert(values={'job_id': job.id,
                'email_address': u'person@nowhere.example.com'}))
        session.refresh(job)
        self.assertEquals(job.cc, ['person@nowhere.example.com'])

        job.cc.append(u'korolev@nauk.su')
        session.flush()
        self.assertEquals(JobCc.query.filter_by(job_id=job.id).count(), 2)

    # https://bugzilla.redhat.com/show_bug.cgi?id=784237
    def test_mail_exception_doesnt_prevent_status_update(self):
        job = data_setup.create_job()
        job.cc.append(u'asdf')
        data_setup.mark_job_running(job)
        data_setup.mark_job_complete(job)

class DistroTreeByFilterTest(unittest.TestCase):

    def setUp(self):
        session.begin()

    def tearDown(self):
        session.commit()

    def test_arch(self):
        excluded = data_setup.create_distro_tree(arch=u'x86_64')
        included = data_setup.create_distro_tree(arch=u'i386')
        session.flush()
        distro_trees = DistroTree.by_filter("""
            <distroRequires>
                <distro_arch op="==" value="i386" />
            </distroRequires>
            """).all()
        self.assert_(excluded not in distro_trees)
        self.assert_(included in distro_trees)

    def test_distro_family(self):
        excluded = data_setup.create_distro_tree(osmajor=u'PinkFootLinux4')
        included = data_setup.create_distro_tree(osmajor=u'OrangeArmLinux6')
        session.flush()
        distro_trees = DistroTree.by_filter("""
            <distroRequires>
                <distro_family op="==" value="OrangeArmLinux6" />
            </distroRequires>
            """).all()
        self.assert_(excluded not in distro_trees)
        self.assert_(included in distro_trees)

    def test_distro_tag_equal(self):
        excluded = data_setup.create_distro_tree(
                distro_tags=[u'INSTALLS', u'STABLE'])
        included = data_setup.create_distro_tree(
                distro_tags=[u'INSTALLS', u'STABLE', u'RELEASED'])
        session.flush()
        distro_trees = DistroTree.by_filter("""
            <distroRequires>
                <distro_tag op="==" value="RELEASED" />
            </distroRequires>
            """).all()
        self.assert_(excluded not in distro_trees)
        self.assert_(included in distro_trees)

    def test_distro_tag_notequal(self):
        excluded = data_setup.create_distro_tree(
                distro_tags=[u'INSTALLS', u'STABLE', u'RELEASED'])
        included = data_setup.create_distro_tree(
                distro_tags=[u'INSTALLS', u'STABLE'])
        session.flush()
        distro_trees = DistroTree.by_filter("""
            <distroRequires>
                <distro_tag op="!=" value="RELEASED" />
            </distroRequires>
            """).all()
        self.assert_(excluded not in distro_trees)
        self.assert_(included in distro_trees)

    def test_distro_variant(self):
        excluded = data_setup.create_distro_tree(variant=u'Server')
        included = data_setup.create_distro_tree(variant=u'ComputeNode')
        session.flush()
        distro_trees = DistroTree.by_filter("""
            <distroRequires>
                <distro_variant op="==" value="ComputeNode" />
            </distroRequires>
            """).all()
        self.assert_(excluded not in distro_trees)
        self.assert_(included in distro_trees)

    def test_distro_name(self):
        excluded = data_setup.create_distro_tree()
        included = data_setup.create_distro_tree()
        session.flush()
        distro_trees = DistroTree.by_filter("""
            <distroRequires>
                <distro_name op="==" value="%s" />
            </distroRequires>
            """ % included.distro.name).all()
        self.assert_(excluded not in distro_trees)
        self.assert_(included in distro_trees)

    def test_distrolabcontroller(self):
        excluded = data_setup.create_distro_tree()
        included = data_setup.create_distro_tree()
        lc = data_setup.create_labcontroller(
                fqdn=u'DistroTreeByFilterTest.test_distrolabcontroller')
        included.lab_controller_assocs.append(LabControllerDistroTree(
                lab_controller=lc, url=u'http://notimportant'))
        session.flush()
        distro_trees = DistroTree.by_filter("""
            <distroRequires>
                <distrolabcontroller op="==" value="%s" />
            </distroRequires>
            """ % lc.fqdn).all()
        self.assert_(excluded not in distro_trees)
        self.assert_(included in distro_trees)

    # https://bugzilla.redhat.com/show_bug.cgi?id=831448
    def test_distrolabcontroller_notequal(self):
        excluded = data_setup.create_distro_tree()
        included = data_setup.create_distro_tree()
        lc = data_setup.create_labcontroller()
        excluded.lab_controller_assocs.append(LabControllerDistroTree(
                lab_controller=lc, url=u'http://notimportant'))
        session.flush()
        distro_trees = DistroTree.by_filter("""
            <distroRequires>
                <distrolabcontroller op="!=" value="%s" />
            </distroRequires>
            """ % lc.fqdn).all()
        self.assert_(excluded not in distro_trees)
        self.assert_(included in distro_trees)

class DistroTreeTest(unittest.TestCase):

    def setUp(self):
        session.begin()
        self.distro_tree = data_setup.create_distro_tree(arch=u'i386')
        self.lc = data_setup.create_labcontroller()
        session.flush()

    def tearDown(self):
        session.commit()

    def test_all_systems_obeys_osmajor_exclusions(self):
        included_system = data_setup.create_system(arch=u'i386',
                lab_controller=self.lc)
        excluded_system = data_setup.create_system(arch=u'i386',
                lab_controller=self.lc,
                exclude_osmajor=[self.distro_tree.distro.osversion.osmajor])
        excluded_system.arch.append(Arch.by_name(u'x86_64'))
        session.flush()
        systems = self.distro_tree.all_systems().all()
        self.assert_(included_system in systems and
                excluded_system not in systems, systems)

    def test_all_systems_obeys_osversion_exclusions(self):
        included_system = data_setup.create_system(arch=u'i386',
                lab_controller=self.lc)
        excluded_system = data_setup.create_system(arch=u'i386',
                lab_controller=self.lc,
                exclude_osversion=[self.distro_tree.distro.osversion])
        excluded_system.arch.append(Arch.by_name(u'x86_64'))
        session.flush()
        systems = self.distro_tree.all_systems().all()
        self.assert_(included_system in systems and
                excluded_system not in systems, systems)

    def test_all_systems_matches_arch(self):
        included_system = data_setup.create_system(arch=u'i386',
                lab_controller=self.lc)
        excluded_system = data_setup.create_system(arch=u'ppc64',
                lab_controller=self.lc)
        session.flush()
        systems = self.distro_tree.all_systems().all()
        self.assert_(included_system in systems and
                excluded_system not in systems, systems)

class DistroTreeSystemsFilterTest(unittest.TestCase):

    def setUp(self):
        session.begin()
        self.lc = data_setup.create_labcontroller()
        self.distro_tree = data_setup.create_distro_tree(arch=u'i386')
        self.user = data_setup.create_user()
        session.flush()

    def tearDown(self):
        session.commit()

    def test_system_vendor(self):
        excluded = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc, vendor=u'AMD')
        included = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc, vendor=u'Intel')
        session.flush()
        systems = self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <system key="vendor" op="=" value="Intel" />
            </hostRequires>
            """).all()
        self.assert_(excluded not in systems)
        self.assert_(included in systems)

    # test cases for <group/> are in bkr.server.test.test_group_xml

    def test_autoprov(self):
        no_power = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        no_power.power = None
        no_lab = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=None)
        included = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        session.flush()
        systems = self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <auto_prov value="True" />
            </hostRequires>
            """).all()
        self.assert_(no_power not in systems)
        self.assert_(no_lab not in systems)
        self.assert_(included in systems)

    def test_system_type(self):
        excluded = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc, type=SystemType.virtual)
        included = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        session.flush()
        systems = self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <system_type op="==" value="Machine" />
            </hostRequires>
            """).all()
        self.assert_(excluded not in systems)
        self.assert_(included in systems)

    def test_hostname(self):
        excluded = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        included = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        session.flush()
        systems = self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <hostname op="==" value="%s" />
            </hostRequires>
            """ % included.fqdn).all()
        self.assert_(excluded not in systems)
        self.assert_(included in systems)

    def test_memory(self):
        excluded = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc, memory=128)
        included = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc, memory=1024)
        session.flush()
        systems = self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <memory op="&gt;=" value="256" />
            </hostRequires>
            """).all()
        self.assert_(excluded not in systems)
        self.assert_(included in systems)

    def test_memory(self):
        excluded = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc, memory=128)
        included = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc, memory=1024)
        session.flush()
        systems = self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <memory op="&gt;=" value="256" />
            </hostRequires>
            """).all()
        self.assert_(excluded not in systems)
        self.assert_(included in systems)

    def test_cpu_count(self):
        excluded = data_setup.create_system(arch=u'i386', shared=True)
        excluded.lab_controller = self.lc
        excluded.cpu = Cpu(processors=1)
        included = data_setup.create_system(arch=u'i386', shared=True)
        included.cpu = Cpu(processors=4)
        included.lab_controller = self.lc
        session.flush()
        systems = list(self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <and>
                    <cpu_count op="=" value="4" />
                </and>
            </hostRequires>
            """))
        self.assert_(excluded not in systems)
        self.assert_(included in systems)
        systems = list(self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <and>
                    <cpu_count op="&gt;" value="2" />
                    <cpu_count op="&lt;" value="5" />
                </and>
            </hostRequires>
            """))
        self.assert_(excluded not in systems)
        self.assert_(included in systems)

    def test_or_lab_controller(self):
        lc1 = data_setup.create_labcontroller(fqdn=u'lab1')
        lc2 = data_setup.create_labcontroller(fqdn=u'lab2')
        lc3 = data_setup.create_labcontroller(fqdn=u'lab3')
        distro_tree = data_setup.create_distro_tree()
        included = data_setup.create_system(arch=u'i386', shared=True)
        included.lab_controller = lc1
        excluded = data_setup.create_system(arch=u'i386', shared=True)
        excluded.lab_controller = lc3
        session.flush()
        systems = list(distro_tree.systems_filter(self.user, """
               <hostRequires>
                <or>
                 <hostlabcontroller op="=" value="lab1"/>
                 <hostlabcontroller op="=" value="lab2"/>
                </or>
               </hostRequires>
            """))
        self.assert_(excluded not in systems)
        self.assert_(included in systems)

    # https://bugzilla.redhat.com/show_bug.cgi?id=831448
    def test_hostlabcontroller_notequal(self):
        desirable_lc = data_setup.create_labcontroller()
        undesirable_lc = data_setup.create_labcontroller()
        included = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=desirable_lc)
        excluded = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=undesirable_lc)
        session.flush()
        systems = list(self.distro_tree.systems_filter(self.user, """
                <hostRequires>
                    <hostlabcontroller op="!=" value="%s" />
                </hostRequires>
                """ % undesirable_lc.fqdn))
        self.assert_(excluded not in systems)
        self.assert_(included in systems)

    def test_arch_equal(self):
        excluded = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        included = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        included.arch.append(Arch.by_name(u'x86_64'))
        session.flush()
        systems = self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <arch op="=" value="x86_64" />
            </hostRequires>
            """).all()
        self.assert_(excluded not in systems)
        self.assert_(included in systems)

    def test_arch_notequal(self):
        excluded = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        excluded.arch.append(Arch.by_name(u'x86_64'))
        included = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        session.flush()
        systems = self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <arch op="!=" value="x86_64" />
            </hostRequires>
            """).all()
        self.assert_(excluded not in systems)
        self.assert_(included in systems)

    def test_numa_node_count(self):
        excluded = data_setup.create_system(arch=u'i386', shared=True)
        excluded.lab_controller = self.lc
        excluded.numa = Numa(nodes=1)
        included = data_setup.create_system(arch=u'i386', shared=True)
        included.numa = Numa(nodes=64)
        included.lab_controller = self.lc
        session.flush()
        systems = list(self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <and>
                    <numa_node_count op=">=" value="32" />
                </and>
            </hostRequires>
            """))
        self.assert_(excluded not in systems)
        self.assert_(included in systems)

    def test_key_equal(self):
        module_key = Key.by_name(u'MODULE')
        with_cciss = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        with_cciss.key_values_string.extend([
                Key_Value_String(module_key, u'cciss'),
                Key_Value_String(module_key, u'kvm')])
        without_cciss = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        without_cciss.key_values_string.extend([
                Key_Value_String(module_key, u'ida'),
                Key_Value_String(module_key, u'kvm')])
        session.flush()
        systems = list(self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <key_value key="MODULE" op="==" value="cciss"/>
            </hostRequires>
            """))
        self.assert_(with_cciss in systems)
        self.assert_(without_cciss not in systems)

    # https://bugzilla.redhat.com/show_bug.cgi?id=679879
    def test_key_notequal(self):
        module_key = Key.by_name(u'MODULE')
        with_cciss = data_setup.create_system(arch=u'i386', shared=True)
        with_cciss.lab_controller = self.lc
        with_cciss.key_values_string.extend([
                Key_Value_String(module_key, u'cciss'),
                Key_Value_String(module_key, u'kvm')])
        without_cciss = data_setup.create_system(arch=u'i386', shared=True)
        without_cciss.lab_controller = self.lc
        without_cciss.key_values_string.extend([
                Key_Value_String(module_key, u'ida'),
                Key_Value_String(module_key, u'kvm')])
        session.flush()
        systems = list(self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <and>
                    <key_value key="MODULE" op="!=" value="cciss"/>
                </and>
            </hostRequires>
            """))
        self.assert_(with_cciss not in systems)
        self.assert_(without_cciss in systems)

    def test_key_present(self):
        module_key = Key.by_name(u'MODULE')
        with_module = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        with_module.key_values_string.extend([
                Key_Value_String(module_key, u'cciss'),
                Key_Value_String(module_key, u'kvm')])
        without_module = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        session.flush()
        systems = list(self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <key_value key="MODULE" op="==" />
            </hostRequires>
            """))
        self.assert_(with_module in systems)
        self.assert_(without_module not in systems)

    def test_key_absent(self):
        module_key = Key.by_name(u'MODULE')
        with_module = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        with_module.key_values_string.extend([
                Key_Value_String(module_key, u'cciss'),
                Key_Value_String(module_key, u'kvm')])
        without_module = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        session.flush()
        systems = list(self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <key_value key="MODULE" op="!=" />
            </hostRequires>
            """))
        self.assert_(with_module not in systems)
        self.assert_(without_module in systems)

    # https://bugzilla.redhat.com/show_bug.cgi?id=729156
    def test_keyvalue_does_not_cause_duplicate_rows(self):
        system = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        disk_key = Key.by_name(u'DISK')
        system.key_values_int.extend([
                Key_Value_Int(disk_key, 30718),
                Key_Value_Int(disk_key, 140011),
                Key_Value_Int(disk_key, 1048570)])
        session.flush()
        query = self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <and>
                    <hostname op="=" value="%s" />
                    <key_value key="DISK" op="&gt;" value="9000" />
                </and>
            </hostRequires>
            """ % system.fqdn)
        self.assertEquals(len(query.all()), 1)
        # with the bug this count comes out as 3 instead of 1,
        # which doesn't sound so bad...
        # but when it's 926127 instead of 278, that's bad
        self.assertEquals(query.count(), 1)

    # https://bugzilla.redhat.com/show_bug.cgi?id=824050
    def test_multiple_nonexistent_keys(self):
        query = self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <and>
                    <key_value key="NOTEXIST1" op="=" value="asdf"/>
                    <key_value key="NOTEXIST2" op="=" value="asdf"/>
                </and>
            </hostRequires>
            """)
        query.all() # don't care about the results, just that it doesn't break

    # https://bugzilla.redhat.com/show_bug.cgi?id=714974
    def test_hypervisor(self):
        baremetal = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc, hypervisor=None)
        kvm = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc, hypervisor=u'KVM')
        session.flush()
        systems = list(self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <and>
                    <hypervisor op="=" value="KVM" />
                </and>
            </hostRequires>
            """))
        self.assert_(baremetal not in systems)
        self.assert_(kvm in systems)
        systems = list(self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <and>
                    <hypervisor op="=" value="" />
                </and>
            </hostRequires>
            """))
        self.assert_(baremetal in systems)
        self.assert_(kvm not in systems)
        systems = list(self.distro_tree.systems_filter(self.user, """
            <hostRequires/>
            """))
        self.assert_(baremetal in systems)
        self.assert_(kvm in systems)

    # https://bugzilla.redhat.com/show_bug.cgi?id=731615
    def test_filtering_by_device(self):
        network_class = data_setup.create_device_class(u'NETWORK')
        with_e1000 = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        with_e1000.devices.append(data_setup.create_device(
                device_class_id=network_class.id,
                vendor_id=u'8086', device_id=u'107c',
                subsys_vendor_id=u'8086', subsys_device_id=u'1376',
                bus=u'pci', driver=u'e1000',
                description=u'82541PI Gigabit Ethernet Controller'))
        with_tg3 = data_setup.create_system(arch=u'i386', shared=True,
                lab_controller=self.lc)
        with_tg3.devices.append(data_setup.create_device(
                device_class_id=network_class.id,
                vendor_id=u'14e4', device_id=u'1645',
                subsys_vendor_id=u'10a9', subsys_device_id=u'8010',
                bus=u'pci', driver=u'tg3',
                description=u'NetXtreme BCM5701 Gigabit Ethernet'))
        session.flush()

        systems = list(self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <device op="=" driver="e1000" />
            </hostRequires>
            """))
        self.assert_(with_e1000 in systems)
        self.assert_(with_tg3 not in systems)

        systems = list(self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <device op="=" type="network" vendor_id="8086" />
            </hostRequires>
            """))
        self.assert_(with_e1000 in systems)
        self.assert_(with_tg3 not in systems)

        systems = list(self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <device op="=" vendor_id="14E4" device_id="1645" />
            </hostRequires>
            """))
        self.assert_(with_e1000 not in systems)
        self.assert_(with_tg3 in systems)

        # this filter does nothing, but at least it shouldn't explode
        systems = list(self.distro_tree.systems_filter(self.user, """
            <hostRequires>
                <device op="=" />
            </hostRequires>
            """))
        self.assert_(with_e1000 in systems)
        self.assert_(with_tg3 in systems)

class UserTest(unittest.TestCase):

    def setUp(self):
        session.begin()
        self.user = data_setup.create_user()
        session.flush()

    def tearDown(self):
        session.commit()

    def test_dictionary_password_rejected(self):
        user = data_setup.create_user()
        try:
            user.root_password = "password"
            self.fail('should raise')
        except ValueError:
            pass


class TaskTypeTest(unittest.TestCase):

    def setUp(self):
        session.begin()

    def tearDown(self):
        session.commit()

    # https://bugzilla.redhat.com/show_bug.cgi?id=816553
    def test_lazy_create_does_not_cause_duplicates(self):
        first = TaskType.lazy_create(type=u'CookieMonster')
        second = TaskType.lazy_create(type=u'CookieMonster')
        self.assert_(first is second)
        self.assertEquals(TaskType.query.filter_by(type=u'CookieMonster').count(), 1)


class GuestRecipeTest(unittest.TestCase):

    def setUp(self):
        session.begin()

    def tearDown(self):
        session.commit()

    def test_locations(self):
        lc = data_setup.create_labcontroller()
        distro_tree = data_setup.create_distro_tree(lab_controllers=[lc],
                urls=[u'nfs://something:/somewhere',
                      u'http://something/somewhere'])
        guest_system = data_setup.create_system(lab_controller=lc,
                type=SystemType.virtual)
        job = data_setup.create_completed_job(distro_tree=distro_tree)
        guest_recipe = GuestRecipe(guestname=u'asdf', guestargs=u'--kvm',
                distro_tree=distro_tree, system=guest_system)
        job.recipesets[0].recipes[0].guests.append(guest_recipe)
        job.recipesets[0].recipes.append(guest_recipe)

        guestxml = guest_recipe.to_xml().toxml()
        self.assert_('location="nfs://something:/somewhere"' in guestxml, guestxml)
        self.assert_('nfs_location="nfs://something:/somewhere"' in guestxml, guestxml)
        self.assert_('http_location="http://something/somewhere"' in guestxml, guestxml)


class TaskPackageTest(unittest.TestCase):

    def setUp(self):
        session.begin()

    def tearDown(self):
        session.commit()

    # https://bugzilla.redhat.com/show_bug.cgi?id=816553
    def test_lazy_create_does_not_cause_duplicates(self):
        first = TaskPackage.lazy_create(package=u'beaker')
        second = TaskPackage.lazy_create(package=u'beaker')
        self.assert_(first is second)
        self.assertEquals(TaskPackage.query.filter_by(package=u'beaker').count(), 1)

class DeviceClassTest(unittest.TestCase):

    def setUp(self):
        session.begin()

    def tearDown(self):
        session.commit()

    # https://bugzilla.redhat.com/show_bug.cgi?id=816553
    def test_lazy_create_does_not_cause_duplicates(self):
        first = DeviceClass.lazy_create(device_class=u'washing_machine')
        second = DeviceClass.lazy_create(device_class=u'washing_machine')
        self.assert_(first is second)
        self.assertEquals(DeviceClass.query.filter_by(device_class=u'washing_machine').count(), 1)

class DeviceTest(unittest.TestCase):

    def setUp(self):
        session.begin()

    def tearDown(self):
        session.commit()

    # https://bugzilla.redhat.com/show_bug.cgi?id=816553
    def test_lazy_create_does_not_cause_duplicates(self):
        device_class = DeviceClass.lazy_create(device_class=u'NETWORK')
        params = dict(device_class_id=device_class.id,
                vendor_id=u'8086', device_id=u'1111',
                subsys_vendor_id=u'8086', subsys_device_id=u'1111',
                bus=u'pci', driver=u'e1000',
                description=u'lol')
        first = Device.lazy_create(**params)
        second = Device.lazy_create(**params)
        self.assert_(first is second)
        self.assertEquals(Device.query.filter_by(**params).count(), 1)

if __name__ == '__main__':
    unittest.main()
