# -*- coding: utf-8 -*-


from odoo import api, fields, tools, models, _
from odoo.fields import Domain
from odoo.exceptions import UserError, ValidationError

from odoo.addons.sync_common.models.common import WHITE_LIST_MODEL, get_md5, check_md5
import functools
import logging

def check_validated(f):
    @functools.wraps(f)
    def check(self, uuid, hw_id, *args, **kargs):
        entity_pool = self.env.get("sync.server.entity")
        entity = entity_pool.get(uuid=uuid)

        if not entity:
            return (False, "Error: Instance does not exist in the server database")
        if not entity.hardware_id or entity.hardware_id != hw_id:
            logging.getLogger('sync.server').warning('Hardware id mismatch: instance %s, db hw_id: %s, hw_id sent: %s, method: %s' % (entity.name, entity.hardware_id, hw_id, f.__name__))
            return (False, 'Error: Hardware ID is incorrect, please contact the support')
        if entity.state == 'updated':
            return (False, 'This instance config has been updated and the update procedure has to be launched at your side to apply the changes.')
        if not entity.state == 'validated':
            return (False, "The instance has not yet been validated by its parent")
        if not entity.user_id.id == int(self.env.uid):
            return (False, "You are not supposed to use this user to connect to the synchronization server")
        return f(self, entity, *args, **kargs)
    f._api_model = True
    check._api_model = True
    return check

class SyncServerManager(models.AbstractModel):
    _name = 'sync.server.sync_manager'
    _description = 'sync.server.sync_manager'
    _order = 'id'


    @check_validated
    def get_last_user_rights_info(self, cr, uid, entity, context=None):
        data = self.env.get('sync_server.user_rights').get_last_user_rights_info(cr, 1, context)
        self._logger.info("::::::::[%s] get UR info sum: %s" % (entity.name, data['sum']))
        return data

    @check_validated
    def get_last_user_rights_file(self, cr, uid, entity, check_sum, context=None):
        ur_obj = self.env.get('sync_server.user_rights')
        ids = ur_obj.search(cr, 1, [('sum', '=', check_sum)], context=context)
        self._logger.info("::::::::[%s] download UR (sum: %s)" % (entity.name, check_sum))
        if not ids:
            return ''
        return ur_obj.get_md5_zip(cr, 1, ids[0], context=context)

    @check_validated
    def get_surveys(self, cr, uid, entity, last_date, context=None):
        survey_obj = self.env.get('sync_server.survey')

        dom = [('activated', '=', True)]
        deactivated_ids = []

        if last_date:
            dom += [('server_write_date', '>', last_date)]
            deactivated_ids = survey_obj.search(cr, 1, ['|', ('active', '=', False), ('activated', '=', False), ('server_write_date', '>', last_date)], context=context)

        survey_ids = survey_obj.search(cr, 1, dom, context=context)
        max_date = survey_obj.get_last_write(cr, 1)

        self._logger.info("::::::::[%s] since %s: %d active surveys, %d inactive" % (entity.name, last_date, len(survey_ids), len(deactivated_ids)))
        if not survey_ids:
            return {'active': [], 'deactivated_ids': deactivated_ids, 'max_date': max_date}

        return {
            'active': survey_obj.read(cr, 1, survey_ids, ['name', 'name_fr',  'profile', 'start_date', 'end_date', 'url_en', 'url_fr', 'server_write_date', 'included_group_txt', 'excluded_group_txt', 'include_condition'], context=context),
            'deactivated_ids': deactivated_ids,
            'max_date': max_date
        }

    @check_validated
    def get_model_to_sync(self, entity):
        """
            Initialize a Push session, send the session id and the list of rule
            @param entity: string : uuid of the synchronizing entity
            @return tuple : (a, b, c):
                    a is True is if the call is succesfull, False otherwise
                    b : is a list of dictionaries that contains all the rule
                        that apply for the synchronizing instance.
                        The format of the dict that contains a single rule definition
                        {
                            'server_id' : integer : id of the rule server side,
                            'name' : string : Name of the rule,
                            'owner_field' : string : Name of the field that is the owner instance of the record
                            'model' : string : Name of the model on which the rule applies,
                            'domain' : string : The domain to filter the record to synchronize, format : standard domain [(),()]
                            'sequence_number' : integer : Sequence number of the rule,
                            'included_fields' : string : list of fields to include, same format as the one needed for export data
                        }

        """
        res = self.env.get('sync_server.sync_rule')._get_rule(entity)
        return (True, res[1], get_md5(res[1]))

    @check_validated
    def receive_package(self, entity, packet):
        """
            Synchronizing entity sending it's packet to the sync server.
            @param entity : string : uuid of the synchronizing entity
            @param packet : Dictionnary : update to send to the server, a pakcet contains at max all the update generate by the same rule
                            format :
                            {
                                'session_id': string : id of the push session, given by get_model_to_sync,
                                'model': string : model's name of the update,
                                'rule_id': string : server_side rule's id given,
                                'fields': string : list of fields to include, format : a list of string, same format as the one needed for export data
                                'load' : list of dictionaries : content of the packet, it the list of values and version
                                        format [{
                                                    'version' : string : version of the update
                                                    'values' : string : list of values in the matching order of fields
                                                             format "['value1', 'value2']"
                                                }, ...]

                            }
            @return: tuple : (a,b)
                     a : boolean : is True is if the call is succesfull, False otherwise
                     b : string : is an error message if a is False
        """
        if self.env.context.get('md5'):
            check_md5(self.env.context['md5'], packet, _('server method receive_package'))
        res = self.env.get("sync.server.update").unfold_package(entity, packet)
        return (True, res)

    @check_validated
    def confirm_update(self, entity, session_id, md5):
        """
            Synchronizing entity confirm that all the packet of this session are sent
            @param entity : string : uuid of the synchronizing entity
            @param session_id : string : the synchronization session_id given at the beginning of the session by get_model_sync.
            @return tuple : (a, b)
                a : boolean : is True is if the call is succesfull, False otherwise
                b : int : sequence number given
        """
        if md5:
            check_md5(md5, session_id, _('server method confirm_update'))

        return self.env.get("sync.server.update").confirm_updates(entity, session_id)


    @check_validated
    def get_max_sequence(self, entity):
        """
            Give to the synchronizing client the sequence of the last complete push, the pull session will pull until this sequence.
            @param entity: string : uuid of the synchronizing entity
            @return a tuple (a, b)
                a : boolean : is True is if the call is succesfull, False otherwise
                b : integer : is the sequence number of the last successfull push session by any entity

        """
        last_seq = self.env.get('sync.server.update').get_last_sequence()
        return (True, last_seq, get_md5(last_seq))

    @check_validated
    def get_update(self, entity, last_seq, offset, max_size, max_seq, recover=False, init_sync=False):
        """
            @param entity : string : uuid of the synchronizing entity
            @param last_seq : integer : Last sequence of update receive succefully in the previous pull session.
            @param offset : integer : Number of record receive after the last_seq
            @param max_size : integer : The number of record max per packet.
            @param max_seq : interger : The sequence max that the update the sync server send to the client in get_max_sequence, to tell the server don't send me
                            newer update then the one already their when the pull session start.
            @param recover : flag : If set to True, will recover self-owned package too.
            @return tuple : (a,b,c)
                a : boolean : True if the call is successfull, False otherwise
                b : dictionnary : Package if there is some update to send remaining, False otherwise
                c : boolean : False if there is some update to send remaining, True otherwise
                              Package format :
                              {
                                    'model': string : model's name of the update
                                    'source_name' : string : source entity's name
                                    'fields' : string : list of fields to include, format : a list of string, same format as the one needed for export data
                                    'sequence' : update's sequence number, a integer
                                    'offset' : update's server offset, used to get next updates
                                    'rule' : rule sequence number (for ordering/grouping)
                                    'fallback_values' : update_master.rule_id.fallback_values
                                    'load' : a list of dict that contain record's values and record's version
                                            [{
                                                'version' : int version of the update
                                                'values' : string : list of values in the matching order of fields
                                                             format "['value1', 'value2']"
                                            }, ..]
                              }

        """
        package = self.env.get("sync.server.update").get_package(entity, last_seq, offset, max_size, max_seq, recover=recover, init_sync=init_sync)
        return (True, package or False, not package, get_md5(package))

    """
        Message synchronization
    """

    @check_validated
    def get_message_rule(self, cr, uid, entity, context=None):
        """
            Initialize a Push message session, send the list of rule
            @param entity: string : uuid of the synchronizing entity
            @return a Tuple (a, b):
                    a : boolean : is True is if the call is succesfull, False otherwise
                    b : list of dictionaries : if a is True, is a list of dictionaries that contains all the rule
                        that apply for the synchronizing instance.
                        The format of the dict that contains a single rule definition
                        {
                            'name' : string : rule's name,
                            'server_id' : integer : server side rule's id ,
                            'model' : string : Name of the model on which the rule applies,
                            'domain' : string : The domain to filter the record to synchronize, format : standard domain [(),()]
                            'sequence_number' : integer : Sequence number of the rule,
                            'remote_call' : string  : name of the method to call when the receiver will execute the message,
                            'arguments' : string : list of fields use in argument for the remote_call, see fields in receive_package
                            'destination_name' : string : Name of the field that will give the destination name,
                        }

        """
        res = self.env.get('sync_server.message_rule')._get_message_rule(cr, uid, entity, context=context)
        return (True, res, get_md5(res))

    @check_validated
    def send_message(self, cr, uid, entity, packet, context=None):
        """
            @param entity: string : uuid of the synchronizing entity
            @param packet: list of dictionaries : a list of message, each message is a dictionnary define like this:
                            {
                                'id' : string : message unique id : ensure that we are not creating or executing 2 times the same message
                                'call' : string : name of the method to call when the receiver will execute the message
                                'dest' : string : name of the destination (generaly a partner Name)
                                'args' : string : Arguments of the call, the format is a a dictionnary that represent is object that generate the message serialiaze in json
                                        see export_data_jso in ir_model_data.py
                            }
            @return: tuple : (a, b):
                     a : boolean : is True is if the call is succesfull, False otherwise
                     b : string : is an informative message
        """
        if context is None:
            context = {}
        if context.get('md5'):
            check_md5(context['md5'], packet, _('server method send_message'))

        return self.env.get('sync.server.message').unfold_package(entity, packet)


    @check_validated
    def get_message_ids(self, entity):
        # UTP-1179: store temporarily this ids of messages to be sent to this entity at the moment of getting the update
        # to avoid having messages that are not belonging to the same "sequence" of the update

        """
        TODO

        msg_ids_tmp = self.env.get("sync.server.message").search([('destination', '=', entity.id), ('sent', '=', False)])

        len_ids = 0
        if msg_ids_tmp:
            len_ids = len(msg_ids_tmp)
            self.env.get('sync.server.entity').write(cr, 1, entity.id, {'msg_ids_tmp': msg_ids_tmp}, context=context)

        self._logger.info("::::::::[%s] stored %s messages" % (entity.name, len_ids))

        return (True, len_ids)
        """
        return (True, 0)

    @check_validated
    def reset_message_ids(self, cr, uid, entity, context=None):
        # UTP-1179: store temporarily this ids of messages to be sent to this entity at the moment of getting the update
        # to avoid having messages that are not belonging to the same "sequence" of the update
        self.env.get('sync.server.entity').write(cr, 1, entity.id, {'msg_ids_tmp': False}, context=context)
        return (True, 0)

    @check_validated
    def get_message(self, cr, uid, entity, max_packet_size, last_seq=None, context=None):
        """
            @param entity: string : uuid of the synchronizing entity
            @param max_packet_size: The number of message max per request.
            @return: a tuple (a, b)
                a : boolean : is True is if the call is succesfull, False otherwise
                b : list of dictionaries : is a list of message serialize into a dictionnary if a is True
                [{
                    'id' : string : message unique id : ensure that we are not creating or executing 2 times the same message
                    'call' : string : name of the method to call when the receiver will execute the message
                    'source' : string : name of the entity that generated the message
                    'args' : string : Arguments of the call, the format is a a dictionnary that represent is object that generate the message serialiaze in json
                                         see export_data_jso in ir_model_data.py
                },..]
        """
        # doing the pull message means that the pull update is finished
        # so last_sequence can be stored
        if last_seq:
            self.env.get('sync.server.entity').write(cr, 1, [entity.id],
                                                      {'last_sequence': last_seq}, context=context)
        res = self.env.get('sync.server.message').get_message_packet(cr, uid,
                                                                      entity, max_packet_size, context=context)
        return (True, res, get_md5(res))

    @check_validated
    def message_received(self, cr, uid, entity, message_ids, context=None):
        """
        #### deprecated used only for migration
            @param entity: string : uuid of the synchronizing entity
            @param message_ids: list of string : The list of message identifier : ['message_uuid1', 'message_uuid2', ....]
            @return: tuple : (a,b)
                     a : boolean : is True is if the call is succesfull, False otherwise
                     b : message : is an error message if a is False

        """
        if context is None:
            context = {}
        if context.get('md5'):
            check_md5(context['md5'], message_ids, _('server method message_received'))
        return (True, self.env.get('sync.server.message').set_message_as_received(cr, 1, entity, message_uuids=message_ids, context=context))

    @check_validated
    def message_received_by_sync_id(self, cr, uid, entity, message_ids, context=None):
        """
            @param entity: string : uuid of the synchronizing entity
            @param message_ids: list of string : The list of message id
            @return: tuple : (a,b)
                     a : boolean : is True is if the call is succesfull, False otherwise
                     b : message : is an error message if a is False

        """
        if context is None:
            context = {}
        if context.get('md5'):
            check_md5(context['md5'], message_ids, _('server method message_received'))
        return (True, self.env.get('sync.server.message').set_message_as_received(cr, 1, entity, message_ids=message_ids, context=context))

    @check_validated
    def message_recover_from_seq(self, cr, uid, entity, start_seq, context=None):
        return (True, self.env.get('sync.server.message').recovery(cr, 1, entity, start_seq, context=context))

    @check_validated
    def sync_success(self, cr, uid, entity, context=None):
        self._logger.info("::::::::[%s] success sync" % (entity.name, ))
        self.env.get('sync.server.entity').write(cr, 1, entity.id, {'date_success_sync': fields.datetime.now()})
        return True
