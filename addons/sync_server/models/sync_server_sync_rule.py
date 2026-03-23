# -*- coding: utf-8 -*-

from collections import defaultdict
from datetime import datetime, timedelta


from odoo import api, fields, tools, models, _
from odoo.fields import Domain
from odoo.exceptions import UserError, ValidationError

from odoo.addons.sync_common.models.common import WHITE_LIST_MODEL


def check_domain(self, rec):
    error = False
    message = f"* Domain syntax... {rec.domain} "
    try:
        domain = eval(rec.domain)
        domain.append(('id', 'in', [1, 2, 3]))
        self.env.get(rec.model_id).search_count(domain)
    except Exception as e:
        message += "failed!\n"
        error = True
    else:
        message += "pass.\n"
    finally:
        if error: message += "Example: ['|', ('name', 'like', 'external_'), ('supplier', '=', True)]\n"
    return (message, error)

class SyncUpdateForcedValues(models.Model):
    _name = 'sync_server.sync_rule.forced_values'
    _description = 'sync_server.sync_rule.forced_values'
    _order = 'id'

    name = fields.Many2one(string="Field Name", comodel_name="ir.model.fields", ondelete="cascade", required=True)
    value = fields.Char(string="Value", size=1024, required=True)
    sync_rule_id = fields.Many2one(string="Sync Rule", comodel_name="sync_server.sync_rule", ondelete="restrict", required=True)


class SyncUpdateFallbackValues(models.Model):
    _name = 'sync_server.sync_rule.fallback_values'
    _description = 'sync_server.sync_rule.fallback_values'
    _order = 'id'

    def _get_fallback_value(self):
        model = self.env.get('ir.model')
        return [(r['model'], r['model']) for r in model.search_read([('model', 'not in', WHITE_LIST_MODEL)], ['model'])]

    name = fields.Many2one(string="Field Name", comodel_name="ir.model.fields", ondelete="cascade", required=True)
    value = fields.Reference(string="Value", selection="_get_fallback_value", required=True)
    sync_rule_id = fields.Many2one(string="Sync Rule", comodel_name="sync_server.sync_rule", ondelete="restrict", required=True)



class SyncUpdateRule(models.Model):
    _name = 'sync_server.sync_rule'
    _description = 'Synchronization Rule'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence_number asc,model_id asc'

    name = fields.Char(string="Rule Name", size=64, required=True, tracking=True)
    model_id = fields.Char(string="Model Name", compute="_compute_model_id", store=True, size=64, readonly=False, inverse="_inverse_model_id")
    model_ref = fields.Many2one(string="Model", comodel_name="ir.model", ondelete="set null")
    applies_to_type = fields.Boolean(string="Applies to type", help="Applies to a group type instead of a specific group")
    group_id = fields.Many2one(string="Group", comodel_name="sync.server.entity_group", ondelete="set null", index=True)
    type_id = fields.Many2one(string="Group Type", comodel_name="sync.server.group_type", ondelete="set null", index=True)
    type_name = fields.Char(string="Group Name", related="type_id.name", readonly=True)
    direction = fields.Selection(string="Directionality", selection=[('up', 'Up'), ('down', 'Down'), ('hqdown', 'HQ Down'), ('bidirectional', 'Bidirectional'), ('bi-private', 'Bidirectional-Private'), ('single-private', 'Single-Private'), ('mission-private', 'Mission-Private')], required=True)
    domain = fields.Text(string="Domain", default="[]")
    owner_field = fields.Char(string="Owner Field", size=64)
    sequence_number = fields.Integer(string="Sequence", required=True)
    included_fields_sel = fields.Many2many(string="Select Fields", comodel_name="ir.model.fields", relation="ir_model_fields_rules_rel", column1="field", column2="name")
    included_fields = fields.Text(string="Fields to include")
    forced_values_sel = fields.One2many(string="Select Forced Values", comodel_name="sync_server.sync_rule.forced_values", inverse_name="sync_rule_id")
    forced_values = fields.Text(string="Values to force")
    fallback_values_sel = fields.One2many(string="Select Fallback Values", comodel_name="sync_server.sync_rule.fallback_values", inverse_name="sync_rule_id")
    fallback_values = fields.Text(string="Fallback values")
    can_delete = fields.Boolean(string="Can delete record?", help="Propagate the delete of old unused records")
    status = fields.Selection(string="Status", selection=[('valid', 'Valid'), ('invalid', 'Invalid')], required=True, default="valid", readonly=True)
    active = fields.Boolean(string="Active", default=False)
    model_ids = fields.Many2many(string="Parents Model", compute="_get_all_model", comodel_name="ir.model", readonly=True)
    handle_priority = fields.Boolean(string="Handle Priority", default=False)
    master_data = fields.Boolean(string="Master Data", default=True)
    direction_usb = fields.Selection(string="Direction", selection=(('rw_to_cp', 'Remote Warehouse to Central Platform'), ('cp_to_rw', 'Central Platform to Remote Warehouse'), ('bidirectional', 'Bidirectional')), help="The direction of the synchronization", default="bidirectional")

    @api.depends('model_ref')
    def _compute_model_id(self):
        for rec in self:
            rec.model_id = rec.model_ref.model

    def _inverse_model_id(self):
        for rec in self:
            rec.model_ref = self.env["ir.model"]._get(rec.model_id)

    @api.depends('model_id')
    def _get_all_model(self):
        def recur_get_model(model):
            res = [model.id]
            for inherit in model.inherited_model_ids:
                res += recur_get_model(inherit)
            return res

        for res in self:
            model_ids = []
            if self.model_id:
                for model in self.env.get('ir.model').search([('model', '=', self.model_id)]):
                    model_ids += recur_get_model(model)
            self.model_ids = model_ids

    #TODO add a last update to send only rule that were updated before => problem of dates
    def _get_rule(self, entity):
        rules_ids = self._compute_rules_to_send(entity)
        return (True, self._serialize_rule(rules_ids))

    def _get_ancestor_group_ids(self, entity):
        return entity._get_ancestor().get_group_ids()

    def _get_children_group_ids(self, entity):
        return entity._get_all_children().get_group_ids()

    def _get_rules_per_group(self, entity):
        if not entity.group_ids:
            raise ValidationError("Your instace does not belong "
                                 "to any group. Instance must be member of at least one "
                                 "group to be able to synchronize.")
        self.env.cr.execute("""SELECT g.id, array_agg(r.id)
                      FROM sync_server_entity_group g
                           JOIN sync_server_group_type t ON (g.type_id=t.id or t.name = 'USB')
                           JOIN sync_server_sync_rule r
                                ON (((r.group_id = g.id AND NOT r.applies_to_type)
                                     OR (r.type_id = t.id AND r.applies_to_type))
                                    AND r.active)
                      WHERE g.id IN %s
                      GROUP BY g.id""", (tuple(x.id for x in entity.group_ids),))
        return dict(self.env.cr.fetchall())

    def _get_groups_per_rule(self, entity):
        self.env.cr.execute("""SELECT r.id, array_agg(g.id)
                      FROM sync_server_entity_group g
                           JOIN sync_server_group_type t ON (g.type_id=t.id)
                           JOIN sync_server_sync_rule r
                                ON (((r.group_id = g.id AND NOT r.applies_to_type)
                                     OR (r.type_id = t.id AND r.applies_to_type))
                                    AND r.active)
                      WHERE g.id IN %s
                      GROUP BY r.id""", (tuple(x.id for x in entity.group_ids),))
        return dict(self.env.cr.fetchall())

    def _compute_rules_to_send(self, entity):
        rules_ids = self._get_rules_per_group(entity)
        ancestor_group = self._get_ancestor_group_ids(entity)
        children_group = self._get_children_group_ids(entity)

        rules_to_send = set()
        for group_id, rule_ids in list(rules_ids.items()):
            for rule in self.browse(rule_ids):
                if rule.direction == 'up' and entity.parent_id: #got a parent in the same group
                    if group_id in ancestor_group:
                        rules_to_send.add(rule.id)
                elif rule.direction == 'down' and entity.children_ids:
                    if group_id in children_group:
                        rules_to_send.add(rule.id)
                elif rule.direction == 'hqdown':
                    if not entity.parent_id and group_id in children_group:
                        rules_to_send.add(rule.id)
                else:
                    rules_to_send.add(rule.id)
        return list(rules_to_send)

    def _compute_rules_to_receive(self, entity):
        rules_ids = self._get_rules_per_group(entity)
        rules_to_send = set()
        for group_id, rule_ids in list(rules_ids.items()):
            rules_to_send.update(rule_ids)

        return list(rules_to_send)

    _rules_serialization_mapping = {
        'id' : 'server_id',
        'name' : 'name',
        'owner_field' : 'owner_field',
        'model_id' : 'model',
        'domain' : 'domain',
        'sequence_number' : 'sequence_number',
        'included_fields' : 'included_fields',
        'can_delete' : 'can_delete',
        'type_name' : 'type',
        'handle_priority' : 'handle_priority',
        'direction': 'direction',
    }

    def _serialize_rule(self, ids):
        if not ids:
            return []
        rules_data = []
        if ids:
            rules_serialization_mapping = dict(
                sum((list(c._rules_serialization_mapping.items())
                     for c in reversed(self.__class__.mro())
                     if hasattr(c, '_rules_serialization_mapping')), [])
            )
            for rule in self.browse(ids):
                rules_data.append(dict(
                    (data, rule[column]) for column, data
                    in list(rules_serialization_mapping.items())
                ))
        return rules_data


    """
        Usability Part
    """

    @api.onchange('included_fields_sel')
    def on_change_included_fields(self):
        """
        print(self.ids)
        print(self._origin.id)
        self.env['ir.model.data'].create({
            'module': 'sd',
            'model': self._name,
            'res_id': self._origin.id,
            'name': f'3456-777-777-444/uuu-toto/{self._origin.id}',
        })
        other = self.search_fetch([], ['domain'])
        for x in other:
            print(x.domain)
        for l2 in self._origin.included_fields_sel:
            print(l2.name)
        print('newe')
        for l in self.included_fields_sel:
            print(l.name)
        """
        return {}
        #values = self.invalidate(ids, model_ref)['value']
        #sel = self._compute_included_field(ids, fields[0][2])
        #values.update( {'included_fields' : sel})
        #return {'value': values}

    def _compute_included_field(self, ids, fields):
        sel = []
        for field in self.env.get('ir.model.fields').read(fields, ['name','model','ttype']):
            name = str(field['name'])
            if field['ttype'] in ('many2one','one2many', 'many2many'): name += '/id'
            sel.append(name)
        return (str(sel) if sel else '')

    def compute_forced_value(self):
        self.write({'active' : False, 'status' : 'invalid' })
        sel = {}
        errors = []
        for rule in self:
            for value in rule.forced_values_sel:
                # Get field information
                field = self.env.get('ir.model.fields').read(value.name.id, ['name','model','ttype'])
                # Try to evaluate value and stringify it on failed
                try: 
                    value = eval(value.value)
                except:
                    value = '"""'+ value.value +'"""'
                # Type checks
                try:
                    if not (isinstance(value, bool) and value == False):
                        # Cast value to the destination type
                        if field['ttype'] in _field2type:
                            value = eval('%s(%s)' % (_field2type[field['ttype']], value))
                        # Evaluate date/datetime
                        if field['ttype'] == 'date':
                            datetime.strptime(value, '%Y-%m-%d')
                        if field['ttype'] == 'datetime':
                            datetime.strptime(value, '%Y-%m-%d %H:%M')
                except Exception as e:
                    sync_log(self, e, 'error')
                    errors.append("%s: type %s incompatible with field of type %s" % (field['name'], type(value).__name__, field['ttype']))
                    continue
                sel[str(field['name'])] = value
            rule.write({'forced_values' : (str(sel) if sel else '')})
        if errors:
            raise ValidationError("\n".join(errors))

        return True

    def compute_fallback_value(self):
        self.write(ids, {'active' : False, 'status' : 'invalid' })
        sel = {}
        errors = []
        for rule in self.browse(ids):
            for value in rule.fallback_values_sel:
                field = self.env.get('ir.model.fields').read(value.name.id, ['name','model','ttype'])

                xml_ids = value.value.get_xml_id()
                name = str(field['name'])
                if field['ttype'] == 'many2one':
                    name += '/id'
                sel[name] = xml_ids[value.value.id]

            self.write(rule.id, {'fallback_values' : (str(sel) if sel else '')})
        if errors:
            raise ValidationError("\n".join(errors))

        return True

    def invalidate(self, ids, model_ref):
        model = ''
        model_ids = []
        if model_ref:
            model = self.env.get('ir.model').browse(model_ref).model
            model_ids = self.env.get(model).get_model_ids()

        return { 'value' : {'active' : False, 'status' : 'invalid', 'model_id' : model, 'model_ids' : model_ids} }

    def create(self, values):

        #for value in values:
        # TODO
        #    if 'included_fields_sel' in value and value.get('included_fields_sel')[0][2]:
        #        value['included_fields'] = self._compute_included_field(cr, uid,
        #                                                                 [], value['included_fields_sel'][0][2])

        new_ids = super().create(values)
        check = new_ids.validate_rules()
        if check['state'] != 'valid':
            raise ValidationError(check['message'])

        return new_ids

    def write(self, values):
        compute_field = values.get('included_fields_sel')
        #if 'included_fields_sel' in values and values.get('included_fields_sel')[0][2]:
        #    values['included_fields'] = self._compute_included_field(ids, values['included_fields_sel'][0][2])


        fields = ['model_id', 'domain', 'sequence_number','included_fields','status', 'direction', 'owner_field', 'forced_values', 'fallback_values']
        rule_to_check = self.env[self._name]
        for rule_data in self:
            dirty = False
            for k in fields:
                if k in values and values[k] != rule_data[k]:
                    dirty = True

            if dirty:
                rule_to_check += rule_data

        if 'applies_to_type' in values:
            if values['applies_to_type']:
                values['group_id'] = False
            else:
                values['type_id'] = False

        res = super().write(values)
        if rule_to_check:
            check = rule_to_check.validate_rules()
            if check['state'] != 'valid':
                raise ValidationError(check['message'])
        return res

    def unlink(self, ids):
        cr.execute("""SAVEPOINT unlink_rule""")
        try:
            return super().unlink(ids)
        except IntegrityError:
            cr.execute("""ROLLBACK TO SAVEPOINT unlink_rule""")
            self._logger.warning("Cannot delete rule(s) %s, disable them" % ids)
            return self.write(ids, {'active':False})

    ## Checkers & Validator ##################################################

    def check_fields(self, title=""):
        self.ensure_one()
        message = title
        error = False
        try:
            included_fields = eval(self.included_fields)
            for field in included_fields:
                base_field = field.split('/')[0]
                if not isinstance(field, str):
                    raise TypeError
                if not self.env.get('ir.model.fields').search_count([('model_id','in', self.model_ids.ids),('name','=',base_field)]):
                    raise KeyError
        except TypeError:
            message += "failed (Fields list should be a list of string)!\n"
            error = True
        except KeyError:
            message += "failed (Field %s doesn't exist for the selected model/object)!\n" % base_field
            error = True
        except Exception:
            message += "failed! (Syntax Error : not a python expression) \n"
            error = True
        else:
            message += "pass.\n"
        finally:
            if error:
                message += "Example: ['name', 'order_line/product_id/id', 'order_line/product_id/name', 'order_line/product_uom_qty']\n"

        return (message, error)

    def check_forced_values(self):
        self.ensure_one()
        error = False
        message = "* Forced values syntax... "
        try:
            forced_value = eval(self.forced_values or '{}')
            if not isinstance(forced_value, dict):
                raise TypeError
        except TypeError:
            message += "failed (Forced values should be a dictionnary)!\n"
            error = True
        except:
            message += "failed! (Syntax error) \n"
            error = True
        else:
            message += "pass.\n"
        finally:
            if error:
                message += "Example: {'field_name' : 'str_value', 'field_name' : 10, 'field_name' : True}\n"

        return (message, error)

    def check_fallback_values(self):
        self.ensure_one()
        error = False
        message = "* Fallback values syntax... "
        try:
            fallback_value = eval(self.fallback_values or '{}')
            if not isinstance(fallback_value, dict):
                raise TypeError
        except TypeError:
            message += "failed (Fallback values should be a dictionnary)!\n"
            error = True
        except:
            message += "failed!\n"
            error = True
        else:
            message += "pass.\n"
        finally:
            if error: message += "Example: {'field_name/id' : 'sd.xml_id'}\n"
            # Sequence is unique
        return (message, error)

    def check_owner_field(self):
        self.ensure_one()
        if self.direction not in ('bi-private', 'single-private', 'mission-private'):
            return ('', False)
        error = False
        message = "* Owner field existence... "
        try:
            fields = []
            ir_model_fields = self.env.get('ir.model.fields')
            included_fields = eval(self.included_fields or '[]')
            if not ir_model_fields.search_count([('name', '=', self.owner_field), ('model_id', 'in', self.model_ids.ids)]):
                raise KeyError
            if self.owner_field not in included_fields and self.owner_field+'/id' not in included_fields:
                raise KeyError
        except KeyError:
            message += "failed!\n"
            message += "The owner field must be present in the included fields!\n"
            error = True
        except:
            raise
            message += "failed!\n"
            message += "Please choose one of these: %s\n" % (", ".join(fields),)
            error = True
        else:
            message += "pass.\n"
        return (message, error)

    check_domain = check_domain

    def validate_rules(self):
        error = False
        message = []
        for rec in self:
            mess, err = self.check_domain(rec)
            error = err or error
            message.append(mess)
            # Check field syntax
            mess, err = self.check_fields(title="* Included fields syntax... ")
            error = err or error
            message.append(mess)
            # Check for valid status
            message.append(_("* Valid status... "))
            if rec.status == 'invalid':
                message.append('failed! Rule has status=invalid\n')
                error=True
            else:
                message.append('pass.\n')
            # Check force values syntax (can be empty)
            mess, err = self.check_forced_values()
            error = err or error
            message.append(mess)
            # Check fallback values syntax (can be empty)
            mess, err = self.check_fallback_values()
            error = err or error
            message.append(mess)
            # Check Owner Field
            mess, err = rec.check_owner_field()
            error = err or error
            message.append(mess)

            if rec.direction == 'single-private' and rec.can_delete:
                error = True
                message.append('Single-Private and Can delete not implemented')

            message.append("* Sequence is unique... ")
            if self.search_count([('sequence_number','=',rec.sequence_number)]) > 1:
                message.append("%s failed!\n" % rec.sequence_number)
                error = True
            else:
                message.append("pass.\n")

        message_header = 'This rule is valid:\n\n' if not error else 'This rule cannot be validated for the following reason:\n\n'
        message_body = ''.join(message)
        return {
            'state': 'valid' if not error else 'invalid',
            'message' : message_header + message_body,
            'sync_rule' : rec.id
        }

    def validate(self):
        message_data = self.validate_rules()
        wiz_id = self.env.get('sync_server.rule.validation.message').create(message_data)
        return {
            'name': 'Rule Validation Message',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'sync_server.rule.validation.message',
            'res_id' : wiz_id,
            'type': 'ir.actions.act_window',
            'context' : context,
            'target' : 'new',
        }

