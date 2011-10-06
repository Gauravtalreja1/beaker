
import unittest
import re
from bkr.client import BeakerWorkflow, BeakerRecipe

class WorkflowTest(unittest.TestCase):

    def setUp(self):
        self.command = BeakerWorkflow(None)

    def test_processPartitions(self):
        recipe = BeakerRecipe()
        recipe.addPartition(name='/mnt/block1',type='part', fs='ext3', size=1024)
        xml = recipe.toxml(prettyxml=True)
        self.assertEquals(xml.strip(), """
<recipe whiteboard="">
	<distroRequires>
		<and/>
	</distroRequires>
	<hostRequires>
		<and/>
	</hostRequires>
	<repos/>
	<partitions>
		<partition fs="ext3" name="/mnt/block1" size="1024" type="part"/>
	</partitions>
</recipe>
        """.strip())

    def test_processTemplate_minimal_recipe(self):
        recipeTemplate = BeakerRecipe()
        recipe = self.command.processTemplate(recipeTemplate,
                [{'name': '/example', 'arches': []}])
        xml = recipe.toxml(prettyxml=True)
        self.assertEquals(xml.strip(), """
<recipe whiteboard="">
	<distroRequires>
		<and/>
	</distroRequires>
	<hostRequires>
		<and/>
	</hostRequires>
	<repos/>
	<partitions/>
	<task name="/distribution/install" role="STANDALONE">
		<params/>
	</task>
	<task name="/example" role="STANDALONE">
		<params/>
	</task>
</recipe>
            """.strip())

    # https://bugzilla.redhat.com/show_bug.cgi?id=723789
    def test_processTemplate_does_not_produce_duplicates(self):
        recipeTemplate = BeakerRecipe()

        # with passed-in distroRequires XML
        recipe = self.command.processTemplate(recipeTemplate,
                requestedTasks=[{'name': '/example', 'arches': []}],
                distroRequires='<distroRequires><distro_name op="=" value="RHEL99-U1" /></distroRequires>')
        xml = recipe.toxml(prettyxml=True)
        self.assertEquals(len(re.findall('<distro_name', xml)), 1, xml)

        # with passed-in hostRequires XML
        recipe = self.command.processTemplate(recipeTemplate,
                requestedTasks=[{'name': '/example', 'arches': []}],
                hostRequires='<hostRequires><hostname op="=" value="lolcat.example.invalid" /></hostRequires>')
        xml = recipe.toxml(prettyxml=True)
        self.assertEquals(len(re.findall('<hostname', xml)), 1, xml)

        # with distroRequires and hostRequires in the template
        recipeTemplate.addBaseRequires(distro='RHEL99-U1', machine='lolcat.example.invalid')
        recipe = self.command.processTemplate(recipeTemplate,
                requestedTasks=[{'name': '/example', 'arches': []}])
        xml = recipe.toxml(prettyxml=True)
        self.assertEquals(len(re.findall('<distro_name', xml)), 1, xml)
        self.assertEquals(len(re.findall('<hostname', xml)), 1, xml)
