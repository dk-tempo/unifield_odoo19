# -*- coding: utf-8 -*-

from collections import defaultdict
from datetime import datetime, timedelta
import psycopg2

from odoo import api, fields, tools, models, _
from odoo.exceptions import UserError, ValidationError



MAX_ACTIVITY_DELAY = timedelta(minutes=5)

class EntityGroup(models.Model):
    """ OpenERP group of entities """

    _name = "sync.server.entity_group"
    _description = "Synchronization Instance Group"

    name = fields.Char(string="Group Name", size=64, required=True)
    entity_ids = fields.Many2many(string="Instances", comodel_name="sync.server.entity", relation="sync_entity_group_rel", column1="group_id", column2="entity_id", domain="[('oc', '=', oc)]")
    type_id = fields.Many2one(string="Group Type", comodel_name="sync.server.group_type", ondelete="restrict", required=True)
    oc = fields.Selection(string="Operational Center", selection=[('oca', 'OCA'), ('ocb', 'OCB'), ('ocba', 'OCBA'), ('ocg', 'OCG'), ('ocp', 'OCP'), ('waca', 'WACA'), ('ubuntu', 'UBUNTU')], required=True)

    def get_group_name(self):
        """ method called by sync_client """

        return [{
            'name': group.name,
            'type': group.type_id.name,
            'oc': group.oc
        } for group in self.search([])
        ]


    @api.constrains('oc', 'entity_ids')
    def _check_instance_oc(self):
        self.env.flush_all()
        self.env.cr.execute('''
            select
                e.name
            from
                sync_server_entity_group grp, sync_entity_group_rel rel, sync_server_entity e
            where
                grp.id in %s and
                rel.group_id = grp.id and
                rel.entity_id = e.id and
                e.oc != grp.oc
            ''', (tuple(self.ids ), ))

        mismatch = [x[0] for x in self.env.cr.fetchall()]
        if mismatch:
            raise ValidationError(_("OC on these instances does not match OC on group: %s",  ", ".join(mismatch)))

    def web_save(self, values, specification: dict[str, dict], next_id=None) -> list[dict]:
        instance_ids = []
        if 'entity_ids' in values:
            instance_ids = self.env['sync.server.entity'].sudo().search([('state', '=', 'validated'), ('group_ids', 'in', self.ids)]).ids
        ret =  super().web_save(values, specification, next_id)

        if len(instance_ids) > 1:
            new_instance_ids = self.env['sync.server.entity'].sudo().search([('state', '=', 'validated'), ('group_ids', 'in', self.ids)]).ids
            if set(instance_ids) != set(new_instance_ids):
                raise ValidationError( _("Sorry you can not change instances list on a group with a least 2 Validated instances"))
        return ret

    _name_uniq = models.Constraint(
        'unique(name)',
        'Group name must be unique',
    )

class Version(models.Model):
    _name = 'sync_server.version'
    _description = 'Patch version'
    _order = 'date desc'


    name = fields.Char(string="Revision", size=256, readonly=True)
    patch = fields.Binary(string="Patch", readonly=True)
    sum = fields.Char(string="Check Sum", size=256, readonly=True)
    date = fields.Datetime(string="Revision Date", readonly=True)
    comment = fields.Text(string="Comment", readonly=True)
    importance = fields.Selection(string="Importance Flag", selection=[('required', 'Required'), ('optional', 'Optional')], readonly=True)
    state = fields.Selection(string="State", selection=[('draft', 'Draft'), ('confirmed', 'Confirmed')], readonly=True, default="draft")

    _name_uniq = models.Constraint(
        'unique(name)',
        'Group name must be unique',
    )

    #def init(self, cr):
    # def _get_last_revision
# def _get_next_revisions

class GroupType(models.Model):
    """ OpenERP type of group of entities """

    _name = "sync.server.group_type"
    _description = "Synchronization Instance Group Type"

    name = fields.Char(string="Type Name", size=64, required=True)

    _name_uniq = models.Constraint(
        'unique(name)',
        'Group name must be unique',
    )


class EntityActivity(models.Model):
    _name = 'sync.server.entity.activity'
    _description = "Instance Activity"
    _log_access = False

    entity_id = fields.Integer(string='Entity db id', index=True)
    datetime = fields.Datetime(string='Last Activity', default=fields.Datetime.now)
    activity = fields.Char(string='Activity', size=128, default='Inactive')

    _entity_id_unique = models.Constraint(
        'unique (entity_id)',
        "Can't have multiple entity activity"
    )

class Entity(models.Model):
    _name = "sync.server.entity"
    _description = "Synchronization Instance"

    @api.model
    def set_activity(self, entity, activity, wait=False):
        now = fields.Datetime.now()
        try:
            if not wait:
                self.env.cr.execute("SAVEPOINT update_entity_last_activity")
                self.env.cr.execute('select id from sync_server_entity_activity where entity_id=%s for update nowait', (entity.id,), log_exceptions=False)
            self.env.cr.execute('update sync_server_entity_activity set datetime=%s, activity=%s where entity_id=%s', (now, activity, entity.id))
        except psycopg2.OperationalError as e:
            if not wait and e.pgcode == '55P03':
                # can't acquire lock: ok the show must go on
                self.env.cr.execute("ROLLBACK TO update_entity_last_activity")
                logging.getLogger('sync.server').info("Can't acquire lock to set last_activity")
                return
            raise

    def _get_activity(self):

        activities = {x.entity_id: x for x in  self.env['sync.server.entity.activity'].sudo().search([('entity_id', 'in', self.ids)])}
        for record in self:
            if record.id in activities:
                activity = activities[record.id]
                instance_activity = activity.activity or ''
                if not activity.datetime:
                    delay = timedelta()
                else:
                    delay = datetime.now() - activity.datetime
                if delay > MAX_ACTIVITY_DELAY and '...' in instance_activity:
                    record.activity = _('%s (stalling)') % instance_activity
                elif instance_activity:
                    record.activity = instance_activity
                record.last_dateactivity = activity.datetime
            else:
                record.activity = _('Inactive')
                record.last_dateactivity = False


    name = fields.Char(string="Instance Name", size=64, required=True, index=True)
    identifier = fields.Char(string="Identifier", size=64, readonly=True, index=True)
    hardware_id = fields.Char(string="Hardware Identifier", size=128, index=True)
    parent_id = fields.Many2one(string="Parent Instance", comodel_name="sync.server.entity", ondelete="cascade", domain="[('oc', '=', oc)]")
    oc = fields.Selection(string="Operational Center", selection=[('oca', 'OCA'), ('ocb', 'OCB'), ('ocba', 'OCBA'), ('ocg', 'OCG'), ('ocp', 'OCP'), ('waca', 'WACA'), ('ubuntu', 'UBUNTU')], required=True)
    group_ids = fields.Many2many(string="Groups", comodel_name="sync.server.entity_group", relation="sync_entity_group_rel", column1="entity_id", column2="group_id", domain="[('oc', '=', oc)]")
    state = fields.Selection(string="State", selection=[('pending', 'Pending'), ('validated', 'Validated'), ('invalidated', 'Invalidated'), ('updated', 'Config updated')])
    email = fields.Char(string="Contact Email", size=512)
    user_id = fields.Many2one(string="User", comodel_name="res.users", ondelete="restrict", required=True)
    children_ids = fields.One2many(string="Children Instances", comodel_name="sync.server.entity", inverse_name="parent_id", readonly=True)
    update_token = fields.Char(string="Update security token", size=256)
    activity = fields.Char(string="Activity", compute="_get_activity", readonly=True)
    last_dateactivity = fields.Datetime(string="Date of last activity", compute="_get_activity", readonly=True)
    date_success_sync = fields.Datetime(string="Date of last success sync", readonly=True)
    parent_left = fields.Integer(string="Left Parent", index=True)
    parent_right = fields.Integer(string="Right Parent", index=True)
    msg_ids_tmp = fields.Text(string="List of temporary ids of message to be pulled")
    version = fields.Integer(string="version", default=lambda *a: 0,)
    last_sequence = fields.Integer(string="Last update sequence pulled", readonly=True, default=lambda *a: 0,)
    country_id = fields.Many2one(string="Country", comodel_name="res.country", ondelete="restrict")
    city = fields.Char(string="City", size=256)
    mission = fields.Char(string="Mission", size=64)
    latitude = fields.Float(string="Latitude", digits=(16, 6))
    longitude = fields.Float(string="Longitude", digits=(16, 6))
    pgversion = fields.Char(string="Postgres Version", size=64, readonly=True)
    instance_level = fields.Selection(string="Instance level", selection=[('section', 'Section'), ('coordo', 'Coordo'), ('project', 'Project')], store=True, compute='_get_instance_level', readonly=True)
    current_user_rights_name = fields.Char(string="UR Version", size=64, readonly=True, index=True)
    version_id = fields.Many2one(string="Unifield Version", comodel_name="sync_server.version", ondelete="set null", readonly=True)



    @api.depends('parent_id', 'parent_id.parent_id')
    def _get_instance_level(self):
        for instance in self:
            if not instance.parent_id:
                instance.instance_level = 'section'
            elif not instance.parent_id.parent_id:
                instance.instance_level = 'coordo'
            else:
                instance.instance_level = 'project'

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        """ from UI allow sort on activity / last_dateactivity fields """

        origin_order = None
        if order and ('last_dateactivity' in order or 'activity' in order):
            origin_order = order
            order = None
        query = super()._search(domain, offset, limit, order, **kwargs)
        if origin_order:
            query.add_join(kind='left join', alias='activity', table='sync_server_entity_activity', condition=tools.SQL('activity.entity_id = sync_server_entity.id'))
            other = []
            same = []
            order_by = []
            for order_part in origin_order.split(','):
                order_part = order_part.strip()
                if order_part.startswith('last_dateactivity'):
                    other.append(order_part.replace('last_dateactivity', 'datetime'))
                elif order_part.startswith('activity'):
                    other.append(order_part)
                else:
                    same.append(order_part)
            if same:
                query.order = self._order_to_sql(same, query)
            else:
                query.order = self.env['sync.server.entity.activity']._order_to_sql(' ,'.join(other), query, alias='activity')
        return query

    @api.model
    def get(self, name=False, uuid=False):
        if uuid:
            return self.search([('identifier', '=', uuid)])
        if name:
            return self.search([('name', '=', name)])
        return False


    def validate_action(self):

        for instance in self:
            oc = instance.oc
            parent_id = instance.parent_id and instance.parent_id.id

            if instance.parent_id and instance.oc != instance.parent_id.oc:
                raise ValidationError(_("OC on %s and %s is not the same !", instance.name, instance.parent_id.name))

            grp_type = []
            for grp in instance.group_ids:
                if grp.oc != oc:
                    raise ValidationError(_("OC on group %s does not match oc on instance %s", grp.name, instance.name))
                if parent_id and grp.type_id.name == 'HQ + MISSION':
                    if parent_id not in [x.id for x in  grp.entity_ids]:
                        raise ValidationError(_("Instance %s: the HQ + Mission group %s must contain the parent instance %s", instance.name, grp.name, instance.parent_id.name))

                if grp.type_id.name == 'MISSION' and instance.parent_id and instance.parent_id.parent_id:
                    if parent_id not in [x.id for x in  grp.entity_ids]:
                        raise ValidationError(_("Instance %s: the Mission group %s must contain the parent instance %s", instance.name, grp.name, instance.parent_id.name))

                grp_type.append(grp.type_id.name)

            if instance.parent_id and instance.parent_id.parent_id.parent_id:
                raise ValidationError(_("An instance cannot have a project for parent"))

            if instance.parent_id and instance.parent_id.parent_id:
                # project
                if len(grp_type) != 3 or set(['OC', 'MISSION', 'HQ + MISSION']) != set(grp_type):
                    raise ValidationError(_("A Project instance must be in exactly 3 groups: OC, MISSION and HQ + MISSION"))
            elif instance.parent_id:
                # coordo
                if len(grp_type) != 4 or set(['OC', 'MISSION', 'HQ + MISSION', 'COORDINATIONS']) != set(grp_type):
                    raise ValidationError(_("A Coordo must be in exactly 4 groups: OC, COORDINATIONS, MISSION and HQ + MISSION"))

        self.with_context(update=False).write({'state': 'validated'})
        return True

    def invalidate_action(self):
        self.with_context(update=False).write({'state': 'invalidated'})
        return True

    def _get_ancestor(self):
        ancestor_ids = []
        def _get_ancestor_rec(entity, ancestor_list):
            if entity and entity.parent_id:
                ancestor_list.append(entity.parent_id.id)
                _get_ancestor_rec(entity.parent_id, ancestor_list)

        _get_ancestor_rec(self, ancestor_ids)
        return self.env[self._name].browse(ancestor_ids)

    def _get_all_children(self):
        res = self.search([('id', 'child_of', self.ids), ('id', 'not in', self.ids)])
        return res

    def get_group_ids(self):
        groups = set()
        for entity in self:
            groups.update([group.id for group in entity.group_ids])
        return list(groups)


'''
    def unlink(self, cr, uid, ids, context=None):
        for rec in self.browse(cr, uid, ids, context=context):
            if rec.parent_id:
                raise osv.except_osv(_("Error!"), _("Can not delete an instance that have children!"))
        return super(entity, self).unlink(cr, uid, ids, context=None)

    def _check_duplicate(self, cr, uid, name, uuid, context=None):
        duplicate_id = self.search(cr, uid, [('user_id', '!=', uid), '|',
                                             ('name', '=', name), ('identifier', '=', uuid)],
                                   limit=1, order='NO_ORDER', context=context)
        return bool(duplicate_id)



    def _check_children(self, cr, uid, entity, uuid_list, context=None):
        children_ids = self._get_all_children(cr, uid, entity.id)
        uuid_child = [child.identifier for child in self.browse(cr, uid, children_ids, context=context)]
        for uuid in uuid_list:
            if not uuid in uuid_child:
                return False
        return True

    def _get_entity_id(self, cr, uid, name, uuid, context=None):
        ids = self.search(cr, uid, [('user_id', '=', uid), '|', ('name', '=', name), ('identifier', '=', uuid)])
        return ids and ids[0] or False

    def get(self, cr, uid, name=False, uuid=False, context=None):
        if uuid:
            return self.search(cr, uid, [('identifier', '=', uuid)], context=context)
        if name:
            return self.search(cr, uid, [('name', '=', name)], context=context)
        return False

    """
        Public interface
    """
    def activate_entity(self, cr, uid, name, identifier, hardware_id, context=None):
        """
            Allow to change uuid,
            and reactivate the link between an local instance and his data on the server
        """
        raise NotImplementedError("See US-1809")

    def update(self, cr, uid, identifier, hardware_id, context=None):
        ids = self.search(cr, uid, [('identifier', '=' , identifier),
                                    ('hardware_id', '=', hardware_id),
                                    ('user_id', '=', uid),
                                    ('state', '=', 'updated')], context=context)
        if not ids:
            return (False, 'No update is ready for your entity. If you cannot synchronize data, check that your parent has validated your registration')

        token = pkg_uuid.uuid4().hex
        self.write(cr, 1, ids, {'update_token' : token}, context=context)
        entity = self.browse(cr, uid, ids, context=context)[0]
        groups = [group.name for group in entity.group_ids]
        # Avoid problems serializing None in XML-RPC
        if entity.parent_id.name is None:
            pname = ""
        else:
            pname = entity.parent_id.name
        data = {
            'name': entity.name,
            'parent': pname,
            'email': entity.email,
            'groups': groups,
            'security_token': token,
        }
        return (True, data)

    def ack_update(self, cr, uid, uuid, hardware_id, token, context=None):
        ids = self.search(cr, uid, [('identifier', '=' , uuid),
                                    ('hardware_id', '=', hardware_id),
                                    ('user_id', '=', uid),
                                    ('state', '=', 'updated'),
                                    ('update_token', '=', token)],
                          order='NO_ORDER', context=context)
        if not ids:
            return (False, 'Ack not valid')
        self.write(cr, 1, ids, {'state' : 'validated'}, context=context)
        return (True, "Instance Validated")

    def _update_level(self, cr, uid, ids, level, context=None):
        cr.execute("update sync_server_entity set instance_level=%s where coalesce(instance_level, '')!=%s and id in %s returning id", (level, level, tuple(ids)))
        if level in ('section', 'coordo'):
            updated_instance_ids = [x[0] for x in cr.fetchall()]
            if updated_instance_ids:
                cr.execute('select id from sync_server_entity where parent_id in %s', (tuple(updated_instance_ids),))
                child_ids = [x[0] for x in cr.fetchall()]
                if child_ids:
                    if level == 'section':
                        new_level = 'coordo'
                    else:
                        new_level = 'project'
                    self._update_level(cr, uid, child_ids, new_level, context=context)

    def _set_instance_level(self, cr, uid, ids, vals, context=None):
        if 'parent_id' in vals and ids:
            if not vals['parent_id']:
                level = 'section'
            else:
                p = self.browse(cr, uid, vals['parent_id'], fields_to_fetch=['parent_id'], context=context)
                if not p.parent_id:
                    level = 'coordo'
                else:
                    level = 'project'
            self._update_level(cr, uid, ids, level)

        return True

    def write(self, cr, uid, ids, vals, context=None):
        if not ids:
            return True
        if not context:
            context = {}

        # Be careful to only put it into state updated when something
        # that needs to be sent down to the client changes. (US-1809)
        groups_list = []
        if context.get('update', False):
            for before in self.browse(cr, uid, ids):
                groups_list += [x.id for x in before.group_ids]
                if ('name' in vals and before.name != vals['name'] or
                    'parent_id' in vals and before.parent_id.id != vals['parent_id'] or
                        'email' in vals and before.email != vals['email']):
                    vals['state'] = 'updated'

        self._set_instance_level(cr, uid, ids, vals, context=context)
        ret = super(entity, self).write(cr, uid, ids, vals, context=context)

        if context.get('update', False):
            new_groups = self.pool.get('sync.server.entity_group').search(cr, uid, [('entity_ids', 'in', ids)], context=context)
            if set(new_groups) != set(groups_list):
                super(entity, self).write(cr, uid, ids, {'state': 'updated'}, context=context)
        return ret

    def create(self, cr, uid, vals, context=None):
        if not context:
            context = {}
        update = context.get('update', False)

        if update:
            vals['state'] = 'updated'

        newid = super(entity, self).create(cr, uid, vals, context=context)
        self._set_instance_level(cr, uid, [newid], vals, context=context)
        self.pool.get('sync.server.entity.activity').create(cr, uid, {'entity_id': newid})
        return newid

    def register(self, cr, uid, data, context=None):
        """
            data = {
                'parent_name' : 'name'
                'group_names' : ['group1', 'group2']
                'identifier' : 'uuid',
                'hardware_id' : 'hardware_id'
                'name' : 'name',
                'email' : 'cur.email',
                'max_size' : '5',
                'oc': 'oca',
            }
        """
        def get_parent(parent_name):
            if parent_name:
                return self.get(cr, uid, name=parent_name, context=context)
            return False

        def get_groups(group_names):
            groups = []
            if group_names:
                for g_name in group_names:
                    group_id = self.pool.get('sync.server.entity_group').get(cr, uid, g_name, context)
                    if group_id:
                        groups.extend(group_id)
                return [(6, 0, groups)]
            return False

        if self._check_duplicate(cr, uid, data['name'], data['identifier'], context=context):
            return (False, "Duplicate Name or identifier, please select another one")

        parent_name = data.pop('parent_name')
        parent_id = get_parent(parent_name)
        parent_id = parent_id and parent_id[0] or False

        if parent_name and not parent_id:
            return (False, "Parent does not exist, please choose an existing one")

        groups_names = data.pop('group_names')
        group_ids = get_groups(groups_names)

        entity_id = self._get_entity_id(cr, uid, data['name'], data['identifier'], context=context)
        data.update({'group_ids' : group_ids, 'parent_id' : parent_id, 'user_id': uid, 'state' : 'pending'})
        if entity_id:
            entity = self.browse(cr, uid, entity_id, context=context)
            if not entity.hardware_id or entity.hardware_id != data['hardware_id']:
                return (False, 'Error: Hardware ID is incorrect, please contact the support')
            res = self.write(cr, 1, [entity_id], data, context=context)
            if res:
                #self._send_registration_email(cr, uid, data, groups_names, context=context)
                return (True, "Modification successfully done, waiting for parent validation")
            else:
                return (False, "Modification failed!")
        else:
            res = self.create(cr, 1, data, context=context)
            if res:
                #self._send_registration_email(cr, uid, data, groups_names, context=context)
                return (True, "Registration successfully done, waiting for parent validation")
            else:
                return (False, "Registration failed!")

    @check_validated
    def get_entity(self, cr, uid, entity, context=None):
        return (True, {
            'name': entity.name,
            'identifier': entity.identifier,
            'parent': entity.parent_id.name or '',
            'email': entity.email,
            'entity_status': entity.state,
            'group': ', '.join([group.name for group in entity.group_ids]),
        })

    @check_validated
    def get_children(self, cr, uid, entity, context=None):
        res = []
        for child in self.browse(cr, uid, self._get_all_children(cr, uid, entity.id), context=context):
            data = {
                'name': child.name,
                'identifier': child.identifier,
                'parent': child.parent_id.name,
                'email': child.email,
                'state': child.state,
                'group': ', '.join([group.name for group in child.group_ids]),
            }
            res.append(data)

        return (True, res)

    @check_validated
    def end_synchronization(self, cr, uid, entity, context=None):
        self.pool.get('sync.server.entity').set_activity(cr, uid, entity, _('Inactive'), wait=True)
        return (True, "Instance %s has finished the synchronization" % entity.identifier)

    @check_validated
    def validate(self, cr, uid, entity, uuid_list, context=None):
        for uuid in uuid_list:
            if not uuid:
                return (False, "Error: One of the instance you want validate has no Identifier, the instance should register or be activated")
        if not self._check_children(cr, uid, entity, uuid_list, context=context):
            return (False, "Error: One of the entity you want to validate is not one of your children")
        ids_to_validate = self.search(cr, uid, [('identifier', 'in',
                                                 uuid_list)], context=context)
        self.write(cr, 1, ids_to_validate, {'state': 'validated'}, context=context)
        self._send_validation_email(cr, uid, entity, ids_to_validate, context=context)
        return (True, "Instance %s are now validated" % ", ".join(uuid_list))

    @check_validated
    def invalidate(self, cr, uid, entity, uuid_list, context=None):
        for uuid in uuid_list:
            if not uuid:
                return (False, "Error: One of the instance you want validate has no Identifier, the instance should register or be activated")
        if not self._check_children(cr, uid, entity, uuid_list, context=context):
            return (False, "Error: One of the entity you want validate is not one of your children")
        ids_to_validate = self.search(cr, uid, [('identifier', 'in',
                                                 uuid_list)], context=context)
        self.write(cr, 1, ids_to_validate, {'state': 'invalidated'}, context=context)
        self._send_invalidation_email(cr, uid, entity, ids_to_validate, context=context)
        return (True, "Instance %s are now invalidated" % ", ".join(uuid_list))

    def is_validated(self, cr, uid, uuid, context=None):
        entity_pool = self.pool.get("sync.server.entity")
        id = entity_pool.get(cr, uid, uuid=uuid)
        if not id:
            return (False, "Error: Instance does not exist in the server database")
        entity = entity_pool.browse(cr, uid, id)[0]
        if entity.state == 'validated':
            return (True, "The instance is validated")
        return (False, "The instance has not yet been validated by its parent")

    @check_validated
    def set_pg_version(self, cr, uid, entity, pg_version, context=None):
        """
            deprecated replaced by set_pg_ur_version
        """
        self.write(cr, 1, entity.id, {'pgversion': pg_version}, context=context)
        return True

    @check_validated
    def set_pg_ur_version(self, cr, uid, entity, pg_version, current_user_rights_name, context=None):
        self.write(cr, 1, entity.id, {'pgversion': pg_version, 'current_user_rights_name': current_user_rights_name}, context=context)
        return True

    def validate_action(self, cr, uid, ids, context=None):
        if not context:
            context = {}

        if isinstance(ids, int):
            ids = [ids]

        for instance in self.browse(cr, uid, ids, fields_to_fetch=['oc', 'group_ids', 'parent_id'], context=context):
            oc = instance.oc
            parent_id = instance.parent_id and instance.parent_id.id

            if instance.parent_id and instance.oc != instance.parent_id.oc:
                raise osv.except_osv(_("Error!"), _("OC on %s and %s is not the same !") % (instance.name, instance.parent_id.name))

            grp_type = []
            for grp in instance.group_ids:
                if grp.oc != oc:
                    raise osv.except_osv(_("Error!"), _("OC on group %s does not match oc on instance %s") % (grp.name, instance.name))
                if parent_id and grp.type_id.name == 'HQ + MISSION':
                    if parent_id not in [x.id for x in  grp.entity_ids]:
                        raise osv.except_osv(_("Error!"), _("Instance %s: the HQ + Mission group %s must contain the parent instance %s") % (instance.name, grp.name, instance.parent_id.name))

                if grp.type_id.name == 'MISSION' and instance.parent_id and instance.parent_id.parent_id:
                    if parent_id not in [x.id for x in  grp.entity_ids]:
                        raise osv.except_osv(_("Error!"), _("Instance %s: the Mission group %s must contain the parent instance %s") % (instance.name, grp.name, instance.parent_id.name))

                grp_type.append(grp.type_id.name)

            if instance.parent_id and instance.parent_id.parent_id.parent_id:
                raise osv.except_osv(_("Error!"), _("An instance cannot have a project for parent"))

            if instance.parent_id and instance.parent_id.parent_id:
                # project
                if len(grp_type) != 3 or set(['OC', 'MISSION', 'HQ + MISSION']) != set(grp_type):
                    raise osv.except_osv(_("Error!"), _("A Project instance must be in exactly 3 groups: OC, MISSION and HQ + MISSION"))
            elif instance.parent_id:
                # coordo
                if len(grp_type) != 4 or set(['OC', 'MISSION', 'HQ + MISSION', 'COORDINATIONS']) != set(grp_type):
                    raise osv.except_osv(_("Error!"), _("A Coordo must be in exactly 4 groups: OC, COORDINATIONS, MISSION and HQ + MISSION"))

        context['update'] = False
        self.write(cr, uid, ids, {'state': 'validated'}, context)
        return True

    def invalidate_action(self, cr, uid, ids, context=None):
        if not context:
            context={}

        context['update'] = False
        self.write(cr, uid, ids, {'state': 'invalidated'}, context)
        return True

    def _send_registration_email(self, cr, uid, data, groups_name, context=None):
        parent_id = data.get('parent_id')
        if not parent_id or not data.get('email'):
            return
        email_from = data.get('email').split(',')[0]
        parent = self.browse(cr, uid, [parent_id], context=context)[0]
        if not parent.email:
            return
        email_to = parent.email.split(',')
        tools.email_send(
            email_from,
            email_to,
            "Instance %s register, need your validation" % data.get('name'),
            """
                    Name : %s
                    Identifier : %s
                    Parent : %s
                    Email : %s
                    Group : %s
                """ % (data.get('name'), data.get('identifier'), parent.name, data.get('email'), ', '.join(groups_name)),
        )

    def _send_validation_email(self, cr, uid, entity, ids_validated, context=None):
        email_from = entity.email
        email_to = []
        for child in self.browse(cr, uid, ids_validated, context=None):
            if child.email:
                email_list = child.email and child.email.split(',') or []
                email_to.extend(email_list)

        if not email_from or not email_to:
            return

        tools.email_send(
            email_from,
            email_to,
            "Your registration has been validated by your parent %s" % entity.name,
            "You can start to synchronize your data."
        )

    def _send_invalidation_email(self, cr, uid, entity, ids_validated, context=None):
        email_from = entity.email
        email_to = []
        for child in self.browse(cr, uid, ids_validated, context=None):
            email_list = child.email and child.email.split(',') or []
            email_to.extend(email_list)

        if not email_from or not email_to:
            return

        tools.email_send(
            email_from,
            email_to,
            "Your registration has been invalidated by your parent %s" % entity.name,
            "you or your parent has been invalidated by a parent, if you need more information please contact them by mail at %s" % entity.email
        )

    def _check_recursion(self, cr, uid, ids, context=None):
        for id in ids:
            visited_branch = set()
            visited_node = set()
            res = self._check_cycle(cr, uid, id, visited_branch, visited_node, context=context)
            if not res:
                return False

        return True

    def _check_cycle(self, cr, uid, id, visited_branch, visited_node, context=None):
        if id in visited_branch: #Cycle
            return False

        if id in visited_node: #Already tested don't work one more time for nothing
            return True

        visited_branch.add(id)
        visited_node.add(id)

        #visit child using DFS
        entities = self.browse(cr, uid, id, context=context)
        for child in entities.children_ids:
            res = self._check_cycle(cr, uid, child.id, visited_branch, visited_node, context=context)
            if not res:
                return False

        visited_branch.remove(id)
        return True

    def get_entities_priorities(self, cr, uid, context=None):
        return dict([
            (rec.name, rec.parent_left)
            for rec in self.browse(cr, uid,
                                   self.search(cr, uid, [], context=context),
                                   context=context)
        ])

    def search(self, cr, uid, args, offset=0, limit=None, order=None, context=None, count=False):
        to_order = False
        if not count and order and order != 'NO_ORDER' and ('last_dateactivity' in order or 'activity' in order):
            to_order = True
            init_offset = offset
            init_limit = limit
            offset = 0
            limit = None
        ids = super(entity, self).search(cr, uid, args, offset, limit, order, context, count)
        if ids and to_order:
            order = order.replace('last_dateactivity', 'datetime')
            limit_str = init_limit and ' limit %d' % init_limit or ''
            offset_str = init_offset and ' offset %d' % init_offset or ''
            cr.execute('select entity_id from sync_server_entity_activity where entity_id in %s order by ' + order + limit_str + offset_str, (tuple(ids),))  # not_a_user_entry
            return [x[0] for x in cr.fetchall()]
        return ids

    _constraints = [
        (_check_recursion, 'Error! You cannot create cycle in entities structure.', ['parent_id']),
    ]

    _sql_constraints = [
        ('identifier_unique', 'UNIQUE(identifier)', "Can't have multiple instances with the same identifier!"),
    ]
'''
