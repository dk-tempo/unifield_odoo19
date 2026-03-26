# -*- coding: utf-8 -*-

from collections import defaultdict
from datetime import datetime, timedelta


from odoo import api, fields, tools, models, _
from odoo.exceptions import UserError, ValidationError

import pprint
pp = pprint.PrettyPrinter(indent=4)
import logging

class SavePullerCache(object):
    def __init__(self, model):
        self.__model__ = model
        self.__cache__ = []
        self.__lock__ = threading.Lock()

    def add(self, entity, updates):
        if not updates:
            return
        if isinstance(updates[0], orm.browse_record):
            update_ids = (x.id for x in updates)
        else:
            update_ids = tuple(updates)
        if isinstance(entity, orm.browse_record):
            entity_id = entity.id
        else:
            entity_id = entity
        with self.__lock__:
            self.__cache__.append( (entity_id, update_ids) )

    def merge(self):
        if not self.__cache__:
            return
        with self.__lock__:
            cache, self.__cache__ = self.__cache__, type(self.__cache__)()
        for entity_id, updates in cache:
            for update_id in updates:
                self.__model__.pool.get('sync.server.puller_logs').create({
                    'update_id': update_id,
                    'entity_id': entity_id,
                })

class SyncServerPullerLogs(models.Model):
    _name = "sync.server.puller_logs"
    _description = 'History of update pull'
    _rec_name = "entity_id"
    _table = 'sync_server_entity_rel'

    _logger = logging.getLogger('sync.server')

    update_id = fields.Integer(string="Update", required=True, index=True)
    entity_id = fields.Integer(string="Instance", required=True, index=True)
    create_date = fields.Datetime('Pull Date')

    def create(self, vals):
        try:
            del vals['create_date']
        except KeyError:
            pass
        return super().create(vals)


class SyncServerUpdate(models.Model):
    """
        States : to_send : need to be sent to the server or the server ack still not received
                 sended : Ack for this update received but session not ended
                 validated : ack for the session of the update received, this update can be deleted
    """
    _name = 'sync.server.update'
    _description = 'sync.server.update'
    _order = 'create_date desc, id desc'
    _logger = logging.getLogger('sync.server')

    # TODO
    #_rec_name = 'source'

    source = fields.Many2one(string="Source Instance", comodel_name="sync.server.entity", ondelete="set null", index=True)
    owner = fields.Many2one(string="Owner Instance", comodel_name="sync.server.entity", ondelete="set null", index=True)
    model = fields.Char(string="Model", size=128, readonly=True, index=True)
    sdref = fields.Char(string="SD ref", size=128, readonly=True, index=True)
    session_id = fields.Char(string="Session Id", size=128)
    sequence = fields.Integer(string="Sequence", index=True)
    #fancy_sequence = fields.Char(string="Sequence", compute="fancy_integer", readonly=True)
    version = fields.Integer(string="Record Version")
    #fancy_version = fields.Char(string="Version", compute="fancy_integer", readonly=True)
    rule_id = fields.Many2one(string="Generating Rule", comodel_name="sync_server.sync_rule", ondelete="restrict", readonly=True, index=True)
    values = fields.Text(string="Values")
    create_date = fields.Datetime(string="Synchro Date/Time", readonly=True, index=True)
    puller_ids = fields.One2many(string="Pulled by", comodel_name="sync.server.puller_logs", inverse_name="update_id")
    fancy_puller_ids = fields.Char(string="Search on Pulled by", compute="_get_puller_ids", search="_src_puller_ids", readonly=True)
    is_deleted = fields.Boolean(string="Is deleted?", index=True)
    force_recreation = fields.Boolean(string="Force record recreation")
    handle_priority = fields.Boolean(string="Handle Priority")
    fields = fields.Text(string="Fields")



    def _get_puller_ids(self):
        for r in self:
            self.fancy_puller_ids = False

    def _src_puller_ids(self, operator, value):
        res = []
        server_entity_obj = self.env.get('sync.server.entity')
        if ';' not in value:
            entity_id = server_entity_obj.search([('name', '=', entity_id)])
            if entity_id:
                res.append(('puller_ids', '=', entity_id.id))
        else:
            list_of_ids = server_entity_obj.search([('name', 'in', value.split(';'))])
            if list_of_ids:
                res.append(('puller_ids', 'in', list_of_ids.ids))
        return res

    _detect_duplicated_updates = models.Constraint(
        'UNIQUE (session_id, rule_id, sdref, owner)',
        'This update is duplicated and has been ignored!',
    )

    def init(self):
        table = tools.SQL.identifier(self._table)
        self.env.cr.execute(tools.SQL(
            "CREATE INDEX IF NOT EXISTS sync_server_update_sequence_id_index ON %s (sequence, id)",
            table
        ))
        self.env.cr.execute(tools.SQL(
            "CREATE INDEX IF NOT EXISTS sync_server_update_model_create_date_id_index ON %s (model, create_date, id)",
            table
        ))
        self.env.cr.execute(tools.SQL(
            "CREATE INDEX IF NOT EXISTS sync_server_update_create_date_id_index ON %s (create_date, id)",
            table
        ))

    # TODO
    #def search_web(self, args=None, offset=0, limit=None, order=None,
    #               context=None, count=False):
    #    return self.exact_search_web(args, offset, limit,
    #                                 order, context=context, count=count)

    # TODO
    def search_with_puller_ids(self, args, puller_ids_arg, offset=0,
                               limit=None, order=None, count=False):
        '''
        in case some puller_ids are in the args, a special threament is
        required to merge the requests in one. This id done inside this method
        '''
        where_clause = ''
        query = self._where_calc(args)
        from_clause, where_clause, where_clause_params = query.get_sql()
        if where_clause:
            where_clause = ''.join((' AND ', where_clause))

        final_params = []
        # DISTINCT is needed because we may enter puller_ids can contain
        # mre than one id, and then an update could be more than one time
        # in the results
        if count:
            final_query = "SELECT count(DISTINCT sync_server_update.id) "
        else:
            final_query = """SELECT DISTINCT sync_server_update.id """

        order_by=''
        if not count:
            if order != 'NO_ORDER':
                order = order or self._order
                if order:
                    order_by = ' ORDER BY %s.%s' % (self._table, order)
            if order:
                # because of the DISTINCT, to be able to order, table column to
                # order is needed in the select
                order_column = '%s.%s' % (self._table, order.split(' ')[0])
                final_query = '%s, %s ' % (final_query, order_column)

        final_query += """FROM sync_server_update INNER JOIN sync_server_entity_rel ON
        sync_server_update.id=sync_server_entity_rel.update_id
        WHERE sync_server_entity_rel.entity_id IN %s"""
        final_params.extend([tuple(puller_ids_arg[0][2])])
        final_params.extend(where_clause_params)
        if not count:
            final_query = final_query + where_clause + order_by + ' LIMIT %s OFFSET %s'
            final_params += [limit,offset]
        else:
            final_query += where_clause

        cr.execute(final_query, final_params)
        if count:
            result = cr.fetchone()
            return result[0] or 0
        return [x[0] for x in cr.fetchall()]

    # TODO
    def TODO_search(self, args=None, offset=0, limit=None, order=None, context=None, count=False):
        '''
        if there is fancy_puller_ids search parameter, do corresponding special
        treatmentwhere_params = []
        if not, do normal search
        '''
        new_args = []
        puller_ids_arg = False
        if args:
            for sub_domain in args:
                if sub_domain[0] == 'fancy_puller_ids':
                    puller_ids_arg = self._src_puller_ids(None, None, args)
                else:
                    new_args.append(sub_domain)
        if puller_ids_arg and len(puller_ids_arg[0])>2:
            return self.search_with_puller_ids(new_args,
                                               puller_ids_arg, offset, limit, order, count, context)

        return super(update, self).search(new_args, offset, limit,
                                          order, context=context, count=count)

    @api.model
    def unfold_package(self, entity, packet):
        """
            Called by receive_package() when client instance try to push its updates.

            @param entity : browse_record(sync.server.entity) : client instance entity
            @param packet : dict : update format packet.
                    Please see sync_server.sync_server.receive_package to get the full documentation
                    of the format.
            @param context : context

            @return : True or raise an error
        """
        self._logger.info("::::::::[%s] is pushing %s updates + %s delete" % (entity.name, len(packet['load']), len(packet['unload'])))
        def safe_create(data):
            self.env.cr.execute("SAVEPOINT update_creation")
            try:
                return self.create(data)
            except:
                self.env.cr.execute("ROLLBACK TO SAVEPOINT update_creation")
            else:
                self.env.cr.execute("RELEASE SAVEPOINT update_creation")
            return None

        entity.set_activity(_('Pushing updates...'))

        normal_updates_count = 0
        for update in packet['load']:
            # Try to detect old packet type and raise an error
            assert 'owner' in update, "Packet field 'owner' absent"
            # Get the id of the owner or 0 if absent from sync.server.entity list
            owner = self.env.get('sync.server.entity').search([('name', '=', update['owner'])])
            owner_id = owner.id if owner else False

            if safe_create({
                'session_id': packet['session_id'],
                'rule_id': packet['rule_id'],
                'source': entity.id,
                'model': packet['model'],
                'sdref' : update['sdref'],
                'version': update['version'],
                'fields': packet['fields'],
                'values': update['values'],
                'owner': owner_id,
                'handle_priority': update['handle_priority'],
                'force_recreation' : update['force_recreation'],
            }):
                normal_updates_count += 1

        delete_updates_count = 0
        for sdref in packet['unload']:
            if safe_create({
                'source': entity.id,
                'model': packet['model'],
                'session_id': packet['session_id'],
                'rule_id': packet['rule_id'],
                'sdref' : sdref,
                'is_deleted' : True,
            }):
                delete_updates_count += 1

        self._logger.info("::::::::[%s] Inserted %d new updates: %d normal(s) and %d delete(s)"
                          % (entity.name, (normal_updates_count+delete_updates_count), normal_updates_count, delete_updates_count))
        return True

    @api.model
    def confirm_updates(self, entity, session_id):
        """
            Called by confirm_update during client instance push process. It set a unique sequence number for all the sent packages.

            @param entity : browse_record(sync.server.entity) : client instance entity
            @param session_id : string : the synchronization session_id given at the beginning of the session by get_model_sync.

            @return : tuple(a, b)
                a : boolean : is True is if the call is succesfull, False otherwise
                b : int : sequence number given
        """
        self._logger.info("::::::::[%s] Data Push :: Confirming updates session: %s" % (entity.name, session_id))
        entity.set_activity(_('Confirm updates...'))

        has_updates = self.search_count([('session_id', '=', session_id), ('source', '=', entity.id), ('sequence', '=', False)])
        sequence = False
        nb_updates = 0
        if has_updates:
            sequence = self._get_next_sequence()
            self.env.cr.execute('''update sync_server_update set sequence=%s where session_id=%s and source=%s and sequence is null''', (sequence, session_id, entity.id))
            nb_updates = self.env.cr.rowcount
        self._logger.info("::::::::[%s] Data Push :: Number of data pushed: %d" % (entity.name, nb_updates))
        if sequence:
            self._logger.info("::::::::[%s] Data Push :: New server's sequence number: %s" % (entity.name, sequence))
        return (True, sequence)

    def _get_next_sequence(self):
        """
            Get a unique sequence number for the next sequence id
            @param cr : cr
            @param uid : uid
            @param context : context

            @return : int : sequence number
        """
        # TODO
        return self.env.get('ir.sequence').next_by_code('sync.server.update')

    def get_last_sequence(self):
        """
            Get the id of the last sequence number in the database

            @return : int : sequence number or 0 if no update exists
        """
        seq = self.search([('sequence', '!=', 0)], order="sequence desc, id desc", limit=1)
        if not seq:
            return 0
        return seq[0].sequence

    def get_update_to_send(self, entity, update_ids, recover=False):
        """
            Called by get_package during the client instance pull process.
            Return a list of browse_record with only the updates that really need to be send to the client.
            It filter according to the rules:
             - rule's directionality is 'up' and update source is a child of entity
             - rule's directionality is 'down' and update source is an ancestor of entity
             - rule's directionality is 'bidirectional' (synchronize every where)
             - rule's directionality is 'bi-private': only the ancestors of update's owner field value
               are allowed to get the update.
            Then, it checks the groups.

            @param entity : browse_record(sync.server.entity) : client instance entity
            @param update_ids : list of update ids
            @param recover : flag : if set to True, update of the same source than the entity who try to pull
                are sent to the entity. Default is False.
            @param context : context

            @return : list of browse record of the updates to send
        """
        update_to_send = []
        ancestor = entity._get_ancestor()
        children = entity._get_all_children()
        for update in self.browse(update_ids):
            if not update.rule_id:
                continue
            if update.rule_id.direction == 'bi-private':
                if update.is_deleted:
                    privates = [entity.id]
                elif not update.owner:
                    privates = []
                else:
                    privates = self.env.get('sync.server.entity')._get_ancestor(update.owner.id) + \
                        [update.owner.id]
            elif update.rule_id.direction == 'single-private' and update.owner:
                privates = [update.owner.id]
            elif update.rule_id.direction == 'mission-private' and update.owner:
                privates = [x for x in
                            self.env.get('sync.server.entity')._get_ancestor(update.owner.id) +
                            [update.owner.id] +
                            self.env.get('sync.server.entity')._get_all_children(update.owner.id)
                            if x != update.source.id
                            ]
            else:
                privates = []

            if (update.rule_id.direction == 'up' and update.source in children) or \
               (update.rule_id.direction in ('hqdown', 'down') and update.source in ancestor) or \
               (update.rule_id.direction == 'bidirectional') or \
               (entity.id in privates) or \
               (recover and entity.id == update.source.id):

                source_rules_ids = self.env.get('sync_server.sync_rule')._get_groups_per_rule(update.source)
                s_group = source_rules_ids.get(update.rule_id.id, [])
                if any(group.id in s_group for group in entity.group_ids):
                    update_to_send.append(update)

        return update_to_send

    @api.model
    def get_package(self, entity, last_seq, offset, max_size, max_seq, recover=False, init_sync=False):
        """
            Called by XML RPC get_update method to give a list of updates to pull to the client instance.

            With optimization, SQL requests to search are made to avoid extra time to find updates.
            The updates are filtered and truncated before being sent to the client.

            @param entity : browse_record(sync.server.entity) : client instance entity
            @param last_seq : integer : Last sequence of update receive succefully in the previous pull session. 
            @param offset : integer : Number of record receive after the last_seq
            @param max_size : integer : The number of record max per packet. 
            @param max_seq : interger : The sequence max that the update the sync server send to the client in get_max_sequence, to tell the server don't send me
                    newer update then the one already their when the pull session start.
            @param recover : flag : If set to True, will recover self-owned package too.
            @param context : context

            @return :
                    Please see sync_server.sync_server.receive_package to get the full documentation
                    of the format.
                     - None when no update need to be sent
                     - A dict that format a packet for the client
        """
        entity.set_activity(_('Pulling updates...'))
        top = entity
        while top.parent_id:
            top = top.parent_id
        tree = top._get_all_children()
        if top not in tree:
            tree += top
        tree.filtered(lambda x: x.id != entity.id)

        # TODO
        #if not tree:
        #    return None

        #tree_str = ','.join(map(str, tree_ids))

        rule_ids = self.env.get('sync_server.sync_rule')._compute_rules_to_receive(entity)
        if not rule_ids:
            return None

        if not recover and init_sync:
            # first sync get only master data
            self.env.cr.execute("select id from sync_server_sync_rule where id in %s and master_data='t'", (tuple(rule_ids) ,))  # not_a_user_entry
            rule_ids = [x[0] for x in self.env.cr.fetchall()]

        if not rule_ids:
            return None

        base_query = """
            SELECT "sync_server_update".id FROM "sync_server_update" INNER JOIN sync_server_sync_rule ON sync_server_sync_rule.id = rule_id WHERE
                sync_server_update.rule_id IN %s
                AND sync_server_update.sequence > %s AND sync_server_update.sequence <= %s
        """

        args = [tuple(rule_ids), last_seq, max_seq]
        ancestor = entity._get_ancestor()
        children = entity._get_all_children()

        # We filter out the updates that have nothing to do with the entity that is synchronizing
        filters = []
        if children:
            filters.append("direction = 'up' AND source IN %s")
            args.append(tuple(children.ids))
        if ancestor:
            filters.append("direction = 'down' AND source IN %s")
            args.append(tuple(ancestor.ids))
            filters.append("direction = 'hqdown' AND source = %s")
            args.append(top.id)
        filters.append("direction = 'bidirectional'")
        if recover:
            filters.append("source = %s")
            args.append(entity.id)
        filters.append("direction = 'bi-private' AND (is_deleted = 't' OR owner IN %s)")
        args.append(tuple(children.ids + [entity.id]))
        filters.append("direction = 'single-private' AND owner = %s ")
        args.append(entity.id)
        filters.append("direction = 'mission-private' AND source != %s AND owner IN %s")
        args += [entity.id, tuple(ancestor.ids + children.ids + [entity.id])]
        base_query += ' AND ((' + ') OR ('.join(filters) + '))'

        ## Recover add own client updates to the list
        if not recover:
            base_query += " AND sync_server_update.source in %s"
            args.append(tuple(tree.ids))

        base_query += " AND sync_server_update.id > %s ORDER BY id ASC, sequence ASC OFFSET %s LIMIT %s"

        ## Search first update which is "master", then find next updates to send
        ids = []

        updates_to_send, updates_master = [], []
        offset_increment = 0
        packet_size = 0

        self._logger.info("::::::::[%s] Data pull get package:: init sync = %s, last_seq = %s, max_seq = %s, offset = %s, max_size = %s" % (entity.name, init_sync, last_seq, max_seq, '/'.join(map(str, offset)), max_size))

        while not ids or packet_size < max_size:
            self.env.cr.execute(base_query, args+[offset[0], offset[1], max_size])
            ids = [x[0] for x in self.env.cr.fetchall()]
            if not ids:
                break
            for update in self.get_update_to_send(entity, ids, recover):
                # There is no more room left in the packet. We have to quit. The next
                #  updates will be retrieved later.
                if packet_size >= max_size:
                    ids = ids[:ids.index(update.id)]
                    break

                # If this update is exactly the same as the previous one, we can pack
                #  them together because they can be executed together. Here we pack them
                #  if they behave the same way (same model, same rule, same source,
                #  same sequence, update type)
                if not updates_master or updates_master[-1].model != update.model or \
                        updates_master[-1].rule_id.id != update.rule_id.id or \
                        updates_master[-1].source.id != update.source.id or \
                        updates_master[-1].sequence != update.sequence or \
                        updates_master[-1].is_deleted != update.is_deleted:
                    updates_master.append(update)
                    updates_to_send.append([update])
                else:
                    updates_to_send[-1].append(update)

                packet_size += 1

            offset = (offset[0], offset[1]+len(ids))
            offset_increment += len(ids)

        if not updates_to_send:
            self._logger.info("::::::::[%s] No (more) update to send" % (entity.name,))
            return None

        # Point of no return
        #for update_to_send in updates_to_send:
            #self._cache_pullers.add(entity, update_to_send)
        for updates_by_type in updates_to_send:
            for update in iter(updates_by_type):
                self.env.get('sync.server.puller_logs').create({
                    'update_id': update.id,
                    'entity_id': entity.id,
                })

        data_packages = []

        # We want to return all the updates we have found so far
        for update_master, update_to_send in zip(updates_master, updates_to_send):

            ## Package template
            data = {
                'model' : update_master.model,
                'source_name' : update_master.source.name,
                'sequence' : update_master.sequence,
                'rule' : update_master.rule_id.sequence_number,
                'offset' : (offset[0], offset_increment),
                'update_id': update_to_send[-1].id
            }

            ## Process & Push all updates in the packet
            if update_master.is_deleted:
                data['unload'] = [update.sdref for update in update_to_send]
                data['type'] = 'delete'
            else:
                complete_fields, forced_values = self.get_additional_forced_field(update_master)
                data.update({
                    'fields' : str(complete_fields),
                    'fallback_values' : update_master.rule_id.fallback_values,
                    'load' : [],
                    'type' : 'import',
                })
                for update in update_to_send:
                    values = dict(list(zip(complete_fields[:len(update.values)], eval(update.values))) + \
                                  list(forced_values.items()))
                    data['load'].append({
                        'sdref' : update.sdref,
                        'version' : update.version,
                        'values' : str([values[k] for k in complete_fields]),
                        'owner_name' : update.owner.name if update.owner else '',
                        'force_recreation' : update.force_recreation,
                        'handle_priority' : update.handle_priority,
                    })

            data_packages.append(data)

        # Just shorten the log into one line
        self._logger.info("::::::::[%s] Data pull :: %s updates" % (entity.name, sum([len(x.get('unload', [])) + len(x.get('load', [])) for x in data_packages])))
        return data_packages


    def get_additional_forced_field(self, update):
        fields = eval(update.fields)
        forced_values = eval(update.rule_id.forced_values or '{}')
        if forced_values:
            fields += list(set(forced_values.keys()) - set(fields))
            obj = self.env.get(update.model)
            for k, v in list(forced_values.items()):
                if obj._fields[k].type  == 'boolean':
                    forced_values[k] = str(v)
        return fields, forced_values

