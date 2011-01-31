<div xmlns:py="http://purl.org/kid/ns#">
<a id="advancedsearch" href="#">Toggle Search</a>
<form
    id="simpleform"
    name="${name}_simple"
    action="${action}"
    method="${method}"
    class="searchbar_form"
    py:attrs="form_attrs" 
    style="display:${simple}"
>
<span py:for="hidden in extra_hiddens or []">
    <input type='hidden' id='${hidden[0]}' name='${hidden[0]}' value='${hidden[1]}' />
</span> 
<table>
    <tr>
    <td><input type="text" name="simplesearch" value="${simplesearch}" class="textfield"/>
    </td>
<td><input type="submit" name="search" value="${simplesearch_label}"/>

    <span style="margin:0 0.5em 0.5em 0.5em;" py:for="quickly_search in quickly_searches">
    ${button_widget.display(value=quickly_search[1],options=dict(label=quickly_search[0]))}
    </span>
    </td>


    </tr>
</table> 
</form>
<form 
    id="searchform"
    name="${name}"
    action="${action}"
    method="${method}"
    class="searchbar_form"
    py:attrs="form_attrs"
    style="display:${advanced}"
>

<span py:for="hidden in extra_hiddens or []">
    <input type='hidden' id='${hidden[0]}' name='${hidden[0]}' value='${hidden[1]}' />
</span> 
<fieldset>
    <legend>Search</legend>
    <table>
    <tr>
    <td>
    <table id="${field_id}">
    <thead>
    <tr> 
    <th  py:for="field in fields"> 
        <span class="fieldlabel" py:content="field.label" />
    </th>
    </tr>
    </thead> 
    <tbody>
    <tr py:for="repetition in repetitions"
        class="${field_class}"
        id="${field_id}_${repetition}">
    <script language="JavaScript" type="text/JavaScript">

        ${field_id}_${repetition} = new SearchBar([${to_json(fields)}],'${search_controller}','${value_for(this_operations_field)}',${extra_callbacks_stringified},${table_search_controllers_stringified},'${value_for(this_searchvalue_field)}','${value_for(keyvaluevalue)}',${search_object}, ${date_picker},false);
        addLoadEvent(${field_id}_${repetition}.initialize);

    </script>
    <td py:for="field in fields">
            <span py:content="field.display(value_for(field),
                    **params_for(field))" />
            <span py:if="error_for(field)" class="fielderror"
                    py:content="error_for(field)" />
            <span py:if="field.help_text" class="fieldhelp"
                    py:content="field_help_text" />
    </td>

    <td>
        <a 
        href="javascript:SearchBarForm.removeItem('${field_id}_${repetition}')">Remove (-)</a>
    </td>
    </tr>
    </tbody>
    </table></td><td>
    <input type="submit" name="Search" value="Search"/> 
    </td>

    </tr>
    <tr>
    <td colspan="2">
    <a id="doclink" href="javascript:SearchBarForm.addItem('${field_id}');">Add ( + )</a>
    </td>
    </tr>
    </table>

<a py:if="enable_custom_columns" id="customcolumns" href="#">Toggle Result Columns</a> 
<div style='display:none'  id='selectablecolumns'>
    <ul class="${field_class}" id="${field_id}">
    <li py:if="col_options" py:for="value,desc in col_options">
        <input py:if="col_defaults.get(value)" type="checkbox" name = "${field_id}_column_${value}" id="${field_id}_column_${value}" value="${value}" checked='checked' />
        <input py:if="not col_defaults.get(value)" type="checkbox" name = "${field_id}_column_${value}" id="${field_id}_column_${value}" value="${value}" />
        <label for="${field_id}_${value}" py:content="desc" />
    </li>  
    </ul>
<a style='margin-left:10px' id="selectnone" href="#">Select None</a>
<a style='margin-left:10px' id="selectall" href="#">Select All</a>
<a style='margin-left:10px' id="selectdefault" href="#">Select Default</a>
</div> 
    </fieldset>  
</form>
<script type="text/javascript">
$(document).ready(function() {

    $('.datepicker').live('mouseover', function(event) { 
        $(this).datepicker({ dateFormat: 'yy-mm-dd', 
                             changeMonth: true,
                             changeYear: true,
                             yearRange: '2008:2012' 
                            }); 
    });
    $('#advancedsearch').click( function() { $('#searchform').toggle('slow');
                                                $('#simpleform').toggle('slow');});



    $('#customcolumns').click( function() { $('#selectablecolumns').toggle('slow'); });
    
    $('#selectnone').click( function() { $("input[name *= 'systemsearch_column_']").removeAttr('checked'); }); 
    $('#selectall').click( function() { $("input[name *= 'systemsearch_column_']").attr('checked',1); });
    $('#selectdefault').click( function() { $("input[name *= 'systemsearch_column_']").each( function() { select_only_default($(this))}) });

    function select_only_default(obj) {
        var defaults = ${default_result_columns}
        var current_item = obj.val()
        var the_name = 'systemsearch_column_'+current_item
            if (defaults[current_item] == 1) {
                $("input[name = '"+the_name+"']").attr('checked',1); 
            } else {
                $("input[name = '"+the_name+"']").removeAttr('checked');  
            }
        }
    });


</script>
</div>
