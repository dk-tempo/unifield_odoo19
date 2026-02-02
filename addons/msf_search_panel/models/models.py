from odoo import api, fields, models
from odoo.fields import Domain

class Base(models.AbstractModel):
    _inherit = 'base'

    @api.model
    def search_panel_get_comodel_parent(self, field_name):
        """Returns parent field name of a many2one field"""
        field = self._fields[field_name]
        if not field or field.type != "many2one":
            return False
        comodel = self.env[field.comodel_name].with_context(hierarchical_naming=False)
        if comodel._parent_name not in comodel._fields:
            return False
        return comodel._parent_name


    @api.model
    def search_panel_select_range_hierarchy(self, field_name, **kwargs):
        """Returns data necessary for the construction of a hierarchized search panel """

        field = self._fields[field_name]
        comodel = self.env[field.comodel_name].with_context(hierarchical_naming=False)
        parent_name = kwargs.get('parent_field', comodel._parent_name)
        displayed_ids = kwargs.get('displayed_ids', False)
        if displayed_ids:
            display_domain = Domain([("id", 'in', displayed_ids)])
        else:
            # If no defined display elements we get the root ids
            display_domain = Domain([(parent_name, '=', False)])
        # Search for displayed elements
        displayed_elements = comodel.search_read(display_domain, ['id', 'display_name', parent_name])
        root_ids = [False]
        values = {
            # Default element to select all records
            "0": {
                "id": False,
                "display_name": "All",
                # We keep both parent_id and parentId because the searchModel code has both due to lazy construction,
                # and some code might depend on that somewhere
                "parent_id": False,
                "parentId": False,
            }
        }
        for element in displayed_elements:
            values[element['id']] = {
                'id': element['id'],
                'display_name': element["display_name"],
                'parent_id': element[parent_name],
                'parentId': element[parent_name],
            }
            if not parent_name in element:
                root_ids.append(element['id'])
        # Get their child ids
        children_groups = comodel.formatted_read_group(domain=[(parent_name, 'in', values.keys())], groupby=[parent_name],
                                     aggregates=[f'{parent_name}:min','id:array_agg'])
        for child_group in children_groups:
            parent_value_id = child_group[f'{parent_name}:min']
            values[parent_value_id]['childrenIds'] = child_group['id:array_agg']

        enable_counters = kwargs.get("enable_counters", False)
        if not enable_counters:
            return {
                "values": values,
                "rootIds": root_ids,
            }

        # Get the associated record count
        model_domain = Domain(kwargs.get('search_domain', []))
        category_domain = Domain(kwargs.get('category_domain', []))
        filter_domain = Domain(kwargs.get('filter_domain', []))
        global_domain = model_domain & category_domain & filter_domain

        return {
            "values": values,
            "rootIds": root_ids,
        }


