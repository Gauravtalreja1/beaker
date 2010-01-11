import turbogears
import beaker


def beaker_version():
   try: 
        return beaker.__version__
   except AttributeError, (e): 
        return 'devel-version'   

def add_custom_stdvars(vars):
    return vars.update({"beaker_version" : beaker_version})

turbogears.view.variable_providers.append(add_custom_stdvars)

