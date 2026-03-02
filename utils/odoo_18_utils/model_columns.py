# -*- coding: utf-8 -*-
from osv import osv
from osv import fields

import inspect

DATA_PLACEHOLDERS = {
    "boolean": False,
    "integer": 0,
    "float": 0.0,
    "char": "\"\"",
    "text": "\"\"",
    "selection": "\"\"",
    "many2one": None,
    "one2many": None,
    "many2many": None,
    "date": None,
    "datetime": None,
}

class model_columns(osv.osv_memory):
    _name = 'model.columns'
    _rec_name = 'Model Data'

    @staticmethod
    def string_cleanup(string):
        # Remove newlines
        result: str = string.replace('\n', '')
        # Remove multiples spaces
        result = ' '.join(result.split())
        # Replace string delimiters
        result = result.replace('"', "'")
        return result

    @staticmethod
    def lambda_cleanup(lambda_obj, type):
        result = inspect.getsource(lambda_obj)
        # Cleanup source info prefixing the actual lambda
        if type == "default":
            result = result.split(': ', 1)[1]
        elif type == "selection":
            # Assuming lambda is the first argument before string
            result = result.split('.selection(', 1)[1]
            result = result.rsplit(', string', 1)[0]
        # Remove potential extra lines
        if "\n" in result:
            result = result.split('\n', 1)[0]
        # Remove potential post-lambda comments
        result = result.rsplit('#', 1)[0]
        return result

    def get_method_inheritance_chain(self, model_obj, method_name, res):
        """
        Retrieve all method overrides in order of execution for a given method and Odoo model
        """
        # Check if method name is valid for object
        if not hasattr(model_obj, method_name):
            res["value"]["method_inheritance_chain"] = f"No method called '{method_name}' found for this class"
            return
        # Retrieve all override methods
        method_string = ""
        parent_classes = inspect.getmro(model_obj.__class__)
        for parent_class in parent_classes:
            # Break when hitting first base framework class
            if str(parent_class) == "<class 'osv.osv.osv'>":
                break
            # Skip base class used repeatedly for odoo class inheritance resolution
            if str(parent_class.__module__) == "osv.osv":
                continue
            # Check if override version is present in source
            # (otherwise inspect.getsource returns base class method code regardless of whether
            # the class actually overrides the method or not)
            if not f"def {method_name}" in inspect.getsource(parent_class):
                continue
            method_string += f"====== CLASS ======\n"
            method_string += f"{parent_class}\n\n"
            method_string += f"{inspect.getsource(getattr(parent_class, method_name))}\n\n"

        res["value"]["method_inheritance_chain"] = method_string


    def onchange_model_name(self, cr, uid, ids, model_name=None, method_name=None, context=None):
        """
        """
        if context is None:
            context = {}
        # Prepare default results
        res = {
            'value': {}
        }

        # Check model_name
        if not model_name:
            res["value"]["columns"] = "Type in model name and click away"
            res["value"]["fields"] = "Type in model name and click away"
            return res
        # Search for model name
        model_obj = self.pool.get(model_name)
        if not model_obj:
            res["value"]["fields"] = "Model not found."
            res["value"]["placeholder_methods"] = "Model not found."
            res["value"]["method_inheritance_chain"] = "Model not found."
            return res

        # == CRUD METHODS ==
        if method_name:
            self.get_method_inheritance_chain(model_obj, method_name, res)

        # == COLUMNS TO FIELDS ==
        # Process model columns
        columns = model_obj._columns
        # String containing new fields definitions
        fields_str = ""
        # List of method names for default,selection,compute,search and inverse methods found in field definitions
        method_list = {
            'default': set(),
            'selection': set(),
            'compute': {},
            'inverse': set(),
            'search': set(),
        }
        for field_name, field_data in columns.items():
            ## Extract field data ##
            # Type
            type = field_data._type
            new_type = type[0].upper() + type[1:]

            attributes = []
            # Get base field attributes
            if field_data.string != 'unknown':
                attributes.append(('string', f'"{field_data.string}"'))
            if field_data.required:
                attributes.append(('required', 'True'))
            if field_data.readonly:
                attributes.append(('readonly', 'True'))
            if field_data.help:
                attributes.append(('help', f'"{self.string_cleanup(field_data.help)}"'))
            if field_data.select:
                attributes.append(('index', True))
            if field_data._domain:
                attributes.append(('domain', f'"{field_data._domain}"'))
            # Default values
            if model_obj._defaults and field_name in model_obj._defaults:
                default_val = model_obj._defaults[field_name]
                # Default strings need to be encased by string delimiters (contrary to ints, bools, etc...)
                if isinstance(default_val, str):
                    default_val = f'"{self.string_cleanup(default_val)}"'
                # Check for lambdas and functions
                if callable(default_val):
                    if default_val.__name__ == "<lambda>":
                        # Cleanup initial field name attribute
                        default_val = self.lambda_cleanup(default_val, "default")
                    # In case a function callback is used instead of lambda.
                    else:
                        default_val = default_val.__name__
                        method_list["default"].add((default_val, type))
                attributes.append(('default', f'{default_val}'))

            # Do field type specific adjustments for attributes (function -> compute, relational...)
            is_compute = field_data.__class__.__name__ == "function"
            is_related = field_data.__class__.__name__ == "related"
            # Selection
            if type == "selection":
                selection_val = field_data.selection
                if callable(selection_val) and selection_val.__name__ == "<lambda>":
                    selection_val = self.lambda_cleanup(selection_val, "selection")
                elif callable(selection_val):
                    selection_val = selection_val.__name__
                    method_list["selection"].add(selection_val)
                attributes.insert(1, ('selection', f'{selection_val}'))
            # Float
            if type == "float" and field_data.digits:
                attributes.insert(1, ('digits', f'{field_data.digits}'))
            # String fields
            if type in ["char", "selection", "text"] and field_data.size:
                attributes.insert(1, ('size', f'{field_data.size}'))
            if type in ["char", "text"] and field_data.translate:
                attributes.insert(1, ('translate', f'{field_data.translate}'))
            # Many2many
            if type == "many2many" and not is_compute:
                attributes.insert(1, ('column2', f'"{field_data._id2}"'))
                attributes.insert(1, ('column1', f'"{field_data._id1}"'))
                attributes.insert(1, ('relation', f'"{field_data._rel}"'))
            # One2many
            if type == "one2many" and not is_compute:
                attributes.insert(1, ('inverse_name', f'"{field_data._fields_id}"'))
            # Many2one
            if type == "many2one" and field_data.ondelete:
                attributes.insert(1, ('ondelete', f'"{field_data.ondelete}"'))
            # Relational
            if type in ["many2one", "one2many", "many2many"]:
                attributes.insert(1, ('comodel_name', f'"{field_data._obj}"'))

            if (is_related or is_compute) and field_data.store:
                attributes.insert(1, ('store', 'True'))
            # Related
            if is_related:
                attributes.insert(1, ('related', f'"{field_data._arg[0]}.{field_data._arg[1]}"'))
            # Compute
            if is_compute:
                if field_data._fnct_search:
                    attributes.insert(1, ('search', f'"{field_data._fnct_search.__name__}"'))
                    method_list["search"].add(field_data._fnct_search.__name__)
                if field_data._fnct_inv:
                    attributes.insert(1, ('inverse', f'"{field_data._fnct_inv.__name__}"'))
                    method_list["inverse"].add(field_data._fnct_inv.__name__)
                attributes.insert(1, ('compute', f'"{field_data._fnct.__name__}"'))
                method_list["compute"].setdefault(field_data._fnct.__name__, []).append((field_name, type, field_data.store))

            # Append new field definition
            fields_str += f"{field_name} = fields.{new_type}("
            for attr in attributes:
                fields_str += f"{attr[0]}={attr[1]}, "
            fields_str += ")\n"
            # Remove ", " in final attribute
            fields_str = ''.join(fields_str.rsplit(', ', 1))

        model_header = []
        for x in ('_name', '_description', '_order'):
            if hasattr(model_obj, x) and getattr(model_obj, x):
                model_header.append(f"{x} = '{getattr(model_obj, x)}'")


        # Add resulting field defs to return val
        res["value"]["fields"] = '\n'.join(model_header) + '\n\n' + fields_str

        # Go over all method names discovered in field definitions to generate method placeholders
        method_placeholders_str = "# Default methods\n" if method_list["default"] else ""
        # Default methods
        for method_info in method_list["default"]:
            method_placeholders_str += (f"def {method_info[0]}(self):\n"
                                        f"\t\"\"\"\"\"\"\n"
                                        f"\treturn {DATA_PLACEHOLDERS[method_info[1]]}\n\n")
        # Dynamic select methods
        method_placeholders_str += "# Selection methods\n" if method_list["selection"] else ""
        for method_name in method_list["selection"]:
            method_placeholders_str += (f"def {method_name}(self):\n"
                                        f"\t\"\"\"\"\"\"\n"
                                        f"\treturn [('option_a', 'Option A'), ('option_b', 'Option B')]\n\n")
        # Compute methods
        method_placeholders_str += "# Compute methods\n" if method_list["compute"] else ""
        for method_name, method_info in method_list["compute"].items():
            temp_method_placeholders_str = (f"def {method_name}(self):\n"
                                        f"\t\"\"\"\"\"\"\n"
                                        f"\tfor record in self:\n")
            stored_compute_flag = False
            for linked_field in method_info:
                temp_method_placeholders_str += f"\t\trecord.{linked_field[0]} = {DATA_PLACEHOLDERS[linked_field[1]]}\n"
                if linked_field[2]:
                    stored_compute_flag = True
            if stored_compute_flag:
                temp_method_placeholders_str = f"@api.depends('')\n{temp_method_placeholders_str}"
            method_placeholders_str += temp_method_placeholders_str + "\n"

        # Search methods
        method_placeholders_str += "# Search methods\n" if method_list["search"] else ""
        for method_name in method_list["search"]:
            method_placeholders_str += (f"def {method_name}(self, operator, value):\n"
                                        f"\t\"\"\"\"\"\"\n"
                                        f"\treturn [('id', operator, value)]\n\n")
        # Inverse methods for computed fields
        method_placeholders_str += "# Inverse methods\n" if method_list["inverse"] else ""
        for method_name in method_list["inverse"]:
            method_placeholders_str += (f"def {method_name}(self):\n"
                                        f"\t\"\"\"\"\"\"\n"
                                        f"\tpass\n\n")

        res["value"]["placeholder_methods"] = method_placeholders_str

        # Return results
        return res

    _columns = {
        'fields': fields.text(
            string='Fields',
            readonly=True,
        ),
        'placeholder_methods': fields.text(
            string='Placeholder methods',
            readonly=True,
        ),
        'model_name': fields.char(
            size=128,
            string='Model name',
        ),
        'method_name': fields.char(
            size=128,
            string='Method name',
        ),
        'method_inheritance_chain': fields.text(
            string='Method Inheritance',
            readonly=True,
        ),
    }


model_columns()
