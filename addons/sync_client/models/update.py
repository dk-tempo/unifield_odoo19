# -*- coding: utf-8 -*-

from odoo import api, fields, tools, models, _
from odoo.exceptions import UserError, ValidationError
import re
import logging

re_subfield_separator = re.compile(r"[./]")


# US-2837: in case update of the following models is received and the
# corresponding object has been deleted, it will be recreated.
# For other models not in this list, they will be set as run and get a message:
# 'Manually set to run by the system. Due to a delete'
OBJ_TO_RECREATE = [
    'res.partner',
    'account.period',
    'ir.model.access',
    'msf_field_access_rights.field_access_rule',
    'msf_field_access_rights.field_access_rule_line',
    'msf_button_access_rights.button_access_rule',
    'ir.rule',
    'hr.payment.method',
    'account.analytic.journal',
    'account.journal',
    'account.mcdb',
    'wizard.template',
    'account.analytic.account',
    'dest.cc.link',
    'replenishment.segment.line.amc',
    'replenishment.segment.line',
    'replenishment.segment.line.amc.month_exp',
    'replenishment.segment.date.generation',
    'account.export.mapping',
    'res.users',
]


class fv_formatter:
    def fmt(self, cr, uid, ids, field_name, arg, context):
        res = {}
        for x in self.read(cr, uid, ids, ['fields', 'values'], context):
            if not x['fields'] or not x['values']:
                res[x['id']] = ''
            else:
                try:
                    values = eval(x['values'])
                    fields = eval(x['fields'])
                    i = 0
                    fmt = ""
                    for f in fields:
                        fmt += f + " -> " + tools.ustr(values[i]) + "\n"
                        i += 1
                    res[x['id']] = fmt
                except:
                    # Exceptions here would come from incorrectly formatted
                    # field/value strings, which will be caught in other places
                    # and logged better there.
                    res[x['id']] = '(exception)'
        return res

class SyncClientRule(models.Model):
    _name = "sync.client.rule"

    _description = 'sync.client.rule'
    _order = 'sequence_number asc'

    server_id = fields.Integer(string="Server ID", required=True, readonly=True)
    name = fields.Char(string="Rule name", size=64, readonly=True)
    model = fields.Char(string="Model", size=64, readonly=True, index=True)
    domain = fields.Text(string="Domain", readonly=True)
    sequence_number = fields.Integer(string="Sequence", readonly=True)
    included_fields = fields.Text(string="Included Fields", readonly=True, default="[]")
    owner_field = fields.Char(string="Owner Field", size=128, readonly=True)
    can_delete = fields.Boolean(string="Can delete record?", readonly=True, help="Propagate the delete of old unused records")
    active = fields.Boolean(string="Active", index=True, default=True)
    type = fields.Char(string="Group Type", size=256)
    handle_priority = fields.Boolean(string="Handle Priority")
    direction = fields.Char(string="Direction", size=128, readonly=True)


    _server_rule_id_unique = models.Constraint(
        'UNIQUE(server_id)',
        'Duplicate rule server id'
    )

    _logger = logging.getLogger('sync.client')

    @api.model
    def save(self, data_list):
        # Get the whole ids of existing and active rules
        remaining_ids = set(self.search([]).ids)

        for vals in (dict(data) for data in data_list):
            assert 'server_id' in vals, "The following rule doesn't seem to have the required field server_id: %s" % vals

            # Check model exists and is not null
            if not vals.get('model'):
                vals['active'] = False
            elif not self.env.get('ir.model').search([('model', '=', vals['model'])]):
                self._logger.debug("The following rule doesn't apply to your database and has been disabled. Reason: model %s does not exists!\n%s" % (vals['model'], vals))
                continue #do not save the rule if there is no valid model
            elif 'active' not in vals:
                vals['active'] = True

            ext_rule = self.search([('server_id','=',vals['server_id']),'|',('active','=',True),('active','=',False)])
            if ext_rule:
                remaining_ids.discard(ext_rule[0].id)
                ext_rule[0].write(vals)
            else:
                self.create(vals)

        # The rest is just disabled
        if remaining_ids:
            self.browse(list(remaining_ids)).write({'active':False})

    def unlink(self):
        return self.write({'active':False})

    _order = 'sequence_number asc'

'''
class update_link(osv.osv_memory):
    _name = 'update.link'
    _description = 'Handling of the Links to Updates Sent and Received'

    def _open_update_list(self, cr, uid, ids, update_type='received', context=None):
        """
        Returns the Update Received or Sent View for the selected entries.
        :param update_type: String. If 'received', will open the Update Received View. Else will open the Update Sent View.
        """
        if context is None:
            context = {}
        if isinstance(ids, int):
            ids = [ids]

        if context.get('active_ids'):
            ids = context.get('active_ids')

        model = context.get('model')
        if model and isinstance(model, str):
            ir_model_obj = self.env.get('ir.model.data')
            ir_model_data_ids = ir_model_obj.search(cr, uid, [('module', '=', 'sd'),
                                                              ('model', '=', model),
                                                              ('res_id', 'in', ids)], context=context)

            # get the names of all the selected entries if possible, else the name of the object
            model_obj = self.env.get(model)
            try:
                obj_names = model_obj.name_get(cr, uid, ids, context=context)
                descr = ' / '.join([x[1] for x in obj_names])
            except KeyError:
                descr = model_obj._description or model_obj._name or ''

            if ir_model_data_ids:
                sdrefs = ir_model_obj.browse(cr, uid, ir_model_data_ids, fields_to_fetch=['name'],
                                             context=context)

                domain = [('sdref', 'in', [sdref.name for sdref in sdrefs])]
        tree_view = update_type == 'received' and 'update_received_tree_view' or 'sync_client_update_to_send_tree_view'
        view_id = ir_model_obj.get_object_reference(cr, uid, 'sync_client', tree_view)
        view_id = view_id and view_id[1] or False
        search_view = update_type == 'received' and 'update_received_search_view' or 'update_sent_search_view'
        search_view_id = ir_model_obj.get_object_reference(cr, uid, 'sync_client', search_view)
        search_view_id = search_view_id and search_view_id[1] or False
        res_model = update_type == 'received' and 'sync.client.update_received' or 'sync.client.update_to_send'
        return {
            'name': '%s %s' % (update_type == 'received' and _('Update Received Monitor') or _('Update Sent Monitor'), descr),
            'type': 'ir.actions.act_window',
            'res_model': res_model,
            'view_type': 'form',
            'view_mode': 'tree,form',
            'view_id': [view_id],
            'search_view_id': [search_view_id],
            'context': context,
            'domain': domain,
            'target': 'current',
        }

    def open_updates_received(self, cr, uid, ids, context):
        return self._open_update_list(cr, uid, ids, update_type='received', context=context)

    def open_updates_sent(self, cr, uid, ids, context):
        return self._open_update_list(cr, uid, ids, update_type='sent', context=context)
'''
