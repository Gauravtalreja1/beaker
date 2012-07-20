<span xmlns:py='http://purl.org/kid/ns#' py:strip='1'>
 <script language="JavaScript" type="text/JavaScript" py:if="not readonly">
    ${name}_0 = new InstallOptions('${prov_osmajor.field_id}', '${prov_osversion.field_id}', '${tg.url('/get_osversions')}');
    addLoadEvent(${name}_0.initialize);
 </script>
 <p>All options are space separated</p>
 <p>Kickstart Metadata are variables passed to cobblers kickstart template engine.  You should check with cobbler for what variables are available</p>
 <p>Kernel Options are passed at the command line for installations.  ksdevice=bootif is an example along with console=ttyS0.</p>
 <p>Kernel Options Post are also command line options but they are for after the installation has completed.</p>
 <p>Commands are inherited from least specific to most specific. ARCH->FAMILY->UPDATE</p>
 <form  name="${name}" action="${tg.url(action)}" method="POST">
  <table class="list" py:if="not readonly">
   <tr>
    <th>Arch</th><td>${display_field_for("prov_arch")}</td>
    <th>Family</th><td>${display_field_for("prov_osmajor")}</td>
    <th>Update</th><td>${display_field_for("prov_osversion")}</td>
   </tr>
   <tr>
    <th>Kickstart Metadata</th>
     <td colspan="5">${display_field_for("prov_ksmeta")}</td>
    </tr>
    <tr>
     <th>Kernel Options</th>
     <td colspan="5">${display_field_for("prov_koptions")}</td>
    </tr>
    <tr>
     <th>Kernel Options Post</th>
      <td colspan="4">${display_field_for("prov_koptionspost")}</td>
      <td>
       ${display_field_for("id")}
       <a class="button" href="javascript:document.${name}.submit();">Add ( + )</a>
      </td>
    </tr>
  </table>
 </form>
 <table class="list">
  <span py:for="arch in provisions.keys()">
   <tr class="list" bgcolor="#F1F1F1">
    <th colspan="3" class="list">Architecture</th><td class="list">${arch}</td>
    <td>
     <span py:if='not readonly' py:strip='1'>
      ${delete_link(dict(system_id=value_for('id'), arch_id=arch.id), 
          attrs=dict(class_='link'), 
          action=tg.url('/remove_install'))}
     </span>
    </td>
   </tr>
   <tr>
    <th colspan="3" class="list">Kickstart Metadata</th>
    <td class="list">
     ${provisions[arch].ks_meta} 
    </td>
   </tr>
   <tr>
    <th colspan="3" class="list">Kernel Options</th>
    <td class="list">
     ${provisions[arch].kernel_options}
    </td>
   </tr>
   <tr>
    <th colspan="3" class="list">Kernel Options Post</th>
    <td class="list">
     ${provisions[arch].kernel_options_post}
    </td>
   </tr>
   <tr>
    <td>&nbsp;</td>
   </tr>
   <span py:for="family in provisions[arch].provision_families.keys()">
    <tr class="list" bgcolor="#F1F1F1">
     <td>&nbsp;</td>
     <th colspan="2" class="list">Family</th>
     <td class="list">${family}</td>
     <td>
      <span py:if='not readonly' py:strip='1'>
       ${delete_link(dict(system_id=value_for('id'), arch_id=arch.id, 
           osmajor_id=family.id), attrs=dict(class_='link'), 
           action=tg.url('/remove_install'))}
      </span>
     </td>
    </tr>
    <tr>
     <td>&nbsp;</td>
     <th colspan="2" class="list">Kickstart Metadata</th>
     <td class="list">
      ${provisions[arch].provision_families[family].ks_meta} 
     </td>
    </tr>
    <tr>
     <td>&nbsp;</td>
     <th colspan="2" class="list">Kernel Options</th>
     <td class="list">
      ${provisions[arch].provision_families[family].kernel_options} 
     </td>
    </tr>
    <tr>
     <td>&nbsp;</td>
     <th colspan="2" class="list">Kernel Options Post</th>
     <td class="list">
      ${provisions[arch].provision_families[family].kernel_options_post} 
     </td>
    </tr>
    <tr>
     <td>&nbsp;</td>
    </tr>
    <span py:for="update in provisions[arch].provision_families[family].provision_family_updates.keys()">
     <tr class="list" bgcolor="#F1F1F1">
      <td>&nbsp;</td>
      <td>&nbsp;</td>
      <th class="list">Update</th>
      <td class="list">${update}</td>
      <td>
       <span py:if='not readonly' py:strip='1'>
        ${delete_link(dict(system_id=value_for('id'), arch_id=arch.id,
            osversion_id=update.id), attrs=dict(class_='link'), 
            action=tg.url('/remove_install'))}
       </span>
      </td>
     </tr>
     <tr>
      <td>&nbsp;</td>
      <td>&nbsp;</td>
      <th class="list">Kickstart Metadata</th>
      <td class="list">
       ${provisions[arch].provision_families[family].provision_family_updates[update].ks_meta} 
      </td>
     </tr>
     <tr>
      <td>&nbsp;</td>
      <td>&nbsp;</td>
      <th class="list">Kernel Options</th>
      <td class="list">
       ${provisions[arch].provision_families[family].provision_family_updates[update].kernel_options} 
      </td>
     </tr>
     <tr>
      <td>&nbsp;</td>
      <td>&nbsp;</td>
      <th class="list">Kernel Options Post</th>
      <td class="list">
       ${provisions[arch].provision_families[family].provision_family_updates[update].kernel_options_post} 
      </td>
     </tr>
    </span>
   </span>
    <tr>
     <td>&nbsp;</td>
    </tr>
  </span>
 </table>
</span>
