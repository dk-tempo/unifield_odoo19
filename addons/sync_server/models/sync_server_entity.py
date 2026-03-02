# -*- coding: utf-8 -*-

from collections import defaultdict
from datetime import datetime, timedelta


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
    instance_level = fields.Selection(string="Instance level", selection=[('section', 'Section'), ('coordo', 'Coordo'), ('project', 'Project')], readonly=True)
    current_user_rights_name = fields.Char(string="UR Version", size=64, readonly=True, index=True)
    version_id = fields.Many2one(string="Unifield Version", comodel_name="sync_server.version", ondelete="set null", readonly=True)


    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        """ from UI allow sort on activity / last_dateactivity fields """

        origin_order = None
        if 'last_dateactivity' in order or 'activity' in order:
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

