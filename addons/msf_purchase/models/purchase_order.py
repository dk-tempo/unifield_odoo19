from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
import time
import json


class PurchaseOrder(models.Model):
    _name = 'purchase.order'
    _description = 'Purchase Order'
    _order = 'id desc'

    # signature_id = fields.Many2one(string="Signature", comodel_name="signature", ondelete="cascade", required=True)
    order_type = fields.Selection(string="Order Type",
                                  selection=[('regular', 'Regular'), ('donation_exp', 'Donation to prevent losses'),
                                             ('donation_st', 'Standard donation'), ('loan', 'Loan'),
                                             ('loan_return', 'Loan Return'), ('in_kind', 'In Kind Donation'),
                                             ('purchase_list', 'Purchase List'), ('direct', 'Direct Purchase Order')],
                                  required=True, default=lambda *a: 'regular', )
    # loan_id = fields.Many2one(string="Linked loan", comodel_name="sale.order", ondelete="set null", readonly=True)
    priority = fields.Selection(string="Priority", selection=[('emergency', 'Emergency'), ('normal', 'Normal'), ('priority', 'Priority')],
                                default=lambda *a: 'normal', )
    categ = fields.Selection(string="Order category",
                             selection=[('medical', 'Medical'), ('log', 'Logistic'), ('service', 'Service'),
                                        ('transport', 'Transport'), ('other', 'Other')], required=True, default=lambda *a: False, )
    details = fields.Char(string="Details", size=86)
    loan_duration = fields.Integer(string="Loan duration", help="Loan duration in months", default=2)
    date_order = fields.Date(string="Creation Date", required=True, help="Date on which this document has been created.",
                             index=True, default=lambda *a: time.strftime('%Y-%m-%d'), )
    name = fields.Char(string="Order Reference", size=64, required=True, readonly=True,
                       help="unique number of the purchase order,computed automatically when the purchase order is created",
                       index=True, default=lambda *a: False, )
    # invoice_ids = fields.Many2many(string="Invoices", comodel_name="account.invoice", relation="purchase_invoice_rel",
    #                                column1="purchase_id", column2="invoice_id", readonly=True,
    #                                help="Invoices generated for a purchase order")
    # order_line = fields.One2many(string="Order Lines", comodel_name="purchase.order.line", inverse_name="order_id")
    # order_line_mismatch = fields.One2many(string="PO Lines Mismatch with Catalogues",
    #                                       comodel_name="purchase.order.line", inverse_name="order_id", readonly=True,
    #                                       domain="['&', '&', ('product_id', '!=', False), ('catalog_mismatch', 'not in', ['conform', '']), '|', ('state', 'not in', ['cancel', 'cancel_r']), ('confirmation_date', '!=', False)]")
    partner_id = fields.Many2one(string="Supplier", comodel_name="res.partner", ondelete="restrict", required=True,
                                 domain="[('id', '!=', company_id)]")
    partner_address_id = fields.Many2one(string="Address", comodel_name="res.partner.address", ondelete="restrict",
                                         required=True, domain="[('partner_id', '=', partner_id)]",
                                         default=lambda self: self.env.context.get('partner_id', False) and
                                                                    self.env.context['partner_id'].address_get(['default'])['default'])
    dest_partner_id = fields.Many2one(string="Destination partner", comodel_name="res.partner", ondelete="set null")
    dest_partner_type = fields.Selection(string="DPO Dest Partner Type", related="dest_partner_id.partner_type",
                                         selection=[('internal', 'Internal'), ('section', 'Inter-section'),
                                                    ('external', 'External'), ('esc', 'ESC'),
                                                    ('intermission', 'Intermission')], readonly=True)
    # invoice_address_id = fields.Many2one(string="Invoicing address", comodel_name="res.partner.address",
    #                                      ondelete="set null", required=True,
    #                                      help="The address where the invoice will be sent.",
    #                                      default=lambda self: self.env.company.partner_id.address_get(['invoice'])['invoice'])
    invoice_method = fields.Selection(string="Invoicing Control",
                                      selection=[('manual', 'Manual'), ('order', 'From Order'),
                                                 ('picking', 'From Picking')], required=True, readonly=True,
                                      help="From Order: a draft invoice will be pre-generated based on the purchase order. The accountant will just have to validate this invoice for control.From Picking: a draft invoice will be pre-generated based on validated receptions.Manual: allows you to generate suppliers invoices by chosing in the uninvoiced lines of all manual purchase orders.",
                                      default=lambda *a: 'picking', )
    # merged_line_ids = fields.One2many(string="Merged line", comodel_name="purchase.order.merged.line",
    #                                   inverse_name="order_id")
    date_confirm = fields.Date(string="Confirmation date")
    allocation_setup = fields.Selection(string="Allocated setup", compute="_get_allocation_setup",
                                        selection=[('allocated', 'Allocated'), ('unallocated', 'Unallocated'),
                                                   ('mixed', 'Mixed')], readonly=True)
    unallocation_ok = fields.Boolean(string="Unallocated PO")
    partner_ref = fields.Char(string="Supplier Reference", size=128)
    short_partner_ref = fields.Char(string="Supplier Reference", compute="_get_short_partner_ref", size=64, readonly=True)
    product_id = fields.Many2one(string="Product", compute="_get_fake", comodel_name="product.product",
                                 ondelete="set null", readonly=True, help="Product to find in the lines")
    no_line = fields.Boolean(string="No line", compute="_get_no_line", readonly=True, default=lambda *a: True, )
    active = fields.Boolean(string="Active", readonly=True, default=True)
    po_from_ir = fields.Boolean(string="Is PO from IR ?", compute="_po_from_x", readonly=True)
    po_from_fo = fields.Boolean(string="Is PO from FO ?", compute="_po_from_x", readonly=True)
    canceled_end = fields.Boolean(string="Canceled End", readonly=True, default=False)
    is_a_counterpart = fields.Boolean(string="Counterpart?",
                                      help="This field is only for indicating that the order is a counterpart", default=False)
    po_updated_by_sync = fields.Boolean(string="PO updated by sync", default=False)
    origin = fields.Text(string="Source Document",
                         help="Reference of the document that generated this purchase order request.")
    parent_order_name = fields.Many2one(string="Parent PO name", comodel_name="purchase.order", ondelete="set null",
                                        help="If the PO is created from a re-source FO, this field contains the relevant original PO name",
                                        default=False)
    project_ref = fields.Char(string="Project Ref.", size=256)
    message_esc = fields.Text(string="ESC Message")
    fnct_project_ref = fields.Char(string="Project Ref.", compute="_get_project_ref", size=256, readonly=True)
    dest_partner_ids = fields.Many2many(string="Customers", comodel_name="res.partner",
                                        relation="res_partner_purchase_order_rel", column1="purchase_order_id", column2="partner_id")
    dest_partner_names = fields.Char(string="Customers", compute="_get_dest_partner_names", size=256, readonly=True)
    split_po = fields.Boolean(string="Created by split PO", readonly=True, default=False)
    sourced_references = fields.Text(string="Sourced references", compute="_get_project_ref", readonly=True)
    # vat_ok = fields.Boolean(string="VAT OK", compute="_get_vat_ok", readonly=True,
    #                         default=lambda self: self.env['unifield.setup.configuration'].get_config().vat_ok, )
    requested_date_in_past = fields.Boolean(string="Requested date in past", compute="_get_requested_date_in_past", readonly=True)
    update_in_progress = fields.Boolean(string="Update in progress", readonly=True, default=False)
    po_confirmed = fields.Boolean(string="PO", readonly=True, default=lambda *a: False, )
    customer_ref = fields.Text(string="Customer Ref.", compute="_get_customer_ref", search="_src_customer_ref", readonly=True)
    short_customer_ref = fields.Text(string="Customer Ref.", compute="_get_short_customer_ref", readonly=True)
    line_count = fields.Integer(string="Line count", compute="_get_line_count", readonly=True)
    date_approve = fields.Date(string="Date Approved", readonly=True,
                               help="Date on which purchase order has been approved", index=True)
    dest_address_id = fields.Many2one(string="Destination Address", comodel_name="res.partner.address",
                                      ondelete="set null",
                                      help="Put an address if you want to deliver directly from the supplier to the customer.In this case, it will remove the warehouse link and set the customer location.",
                                      default=lambda self: self.env.company.partner_id.address_get(['delivery'])['delivery'])
    # warehouse_id = fields.Many2one(string="Warehouse", comodel_name="stock.warehouse", ondelete="set null")
    # location_ids = fields.Many2many(string="Destination", compute="_get_location_data", comodel_name="stock.location",
    #                                 readonly=True)
    location_names = fields.Char(string="Destination", compute="_get_location_data", size=256, readonly=True,
                                 help="This location is set according to the origin of the line(s) of the document. It can have 'Input', 'Cross Docking', 'Non-Stockable' and/or 'Service' as data")
    # pricelist_id = fields.Many2one(string="Pricelist", comodel_name="product.pricelist", ondelete="set null",
    #                                required=True,
    #                                help="The pricelist sets the currency used for this purchase order. It also computes the supplier price for the selected products/quantities.",
    #                                default=lambda self: self.env.context.get('partner_id', False) and self.env['res.partner'].browse(cr, uid, self.env.context['partner_id']).property_product_pricelist_purchase.id, )
    state = fields.Selection(string="Order State", compute="_get_less_advanced_line_state", store=True,
                             selection=[('draft', 'Draft'), ('draft_p', 'Draft-p'), ('validated', 'Validated'),
                                        ('validated_p', 'Validated-p'), ('sourced', 'Sourced'),
                                        ('sourced_p', 'Sourced-p'), ('confirmed', 'Confirmed'),
                                        ('confirmed_p', 'Confirmed-p'), ('done', 'Closed'), ('cancel', 'Cancelled')],
                             readonly=True, help="The state of the purchase order or the quotation request. A quotation is a purchase order in a 'Draft' state. Then the order has to be confirmed by the user, the state switch to 'Confirmed'. Then the supplier must confirm the order to change the state to 'Approved'. When the purchase order is paid and received, the state becomes 'Done'. If a cancel action occurs in the invoice or in the reception of goods, the state becomes in exception.",
                             index=True, default="draft")
    rfq_state = fields.Selection(string="Order State", compute="_get_less_advanced_line_state", store=True,
                                 selection=[('draft', 'Draft'), ('sent', 'Sent'), ('updated', 'Updated'),
                                            ('done', 'Closed'), ('cancel', 'Cancelled')], readonly=True, index=True, default="draft")
    validator = fields.Many2one(string="Validated by", comodel_name="res.users", ondelete="set null", readonly=True)
    notes = fields.Text(string="Notes")
    # picking_ids = fields.One2many(string="Picking List", comodel_name="stock.picking", inverse_name="purchase_id",
    #                               readonly=True,
    #                               help="This is the list of picking list that have been generated for this purchase")
    shipped = fields.Boolean(string="Received", readonly=True, help="It indicates that a picking has been done", index=True, default=0)
    shipped_rate = fields.Float(string="Received", compute="_shipped_rate", digits=(16, 2), readonly=True)
    invoiced = fields.Boolean(string="Invoiced", compute="_invoiced", readonly=True,
                              help="It indicates that an invoice has been generated", default=0)
    invoiced_rate = fields.Float(string="Invoiced", compute="_invoiced_rate", digits=(16, 2), readonly=True)
    minimum_planned_date = fields.Date(string="Expected Date", compute="_minimum_planned_date",
                                       inverse="_set_minimum_planned_date", store=True,
                                       help="This is computed as the minimum scheduled date of all purchase order lines' products.",
                                       index=True)
    has_tax_at_line_level = fields.Boolean(string="Tax at line", compute="_amount_all", store=True, readonly=True)
    amount_untaxed = fields.Float(string="Untaxed Amount", compute="_amount_all", store=True, digits=(16, 2),
                                  readonly=True, help="The amount without tax")
    amount_tax = fields.Float(string="Taxes", compute="_amount_all", store=True, digits=(16, 2), readonly=True, help="The tax amount")
    amount_total = fields.Float(string="Total", compute="_amount_all", store=True, digits=(16, 2), readonly=True, help="The total amount")
    amount_total_tender_currency = fields.Float(string="Total (Comparison Currency)", compute="_amount_all", store=True,
                                                digits=(16, 2), readonly=True, help="The total amount using the tender's currency for comparison")
    # fiscal_position = fields.Many2one(string="Fiscal Position", comodel_name="account.fiscal.position",
    #                                   ondelete="set null")
    create_uid = fields.Many2one(string="Responsible", comodel_name="res.users", ondelete="set null")
    company_id = fields.Many2one(string="Company", comodel_name="res.company", required=True, index=True,
                                 default=lambda self: self.env.company)
    stock_take_date = fields.Date(string="Date of Stock Take")
    fixed_order_type = fields.Char(string="Possible order types", compute="_is_fixed_type", store=True, size=256,
                                   readonly=True, default=lambda *a: json.dumps([]), )
    delivery_requested_date = fields.Date(string="Requested Delivery Date", required=True)
    delivery_requested_date_modified = fields.Date(string="Estimated Delivery Date")
    delivery_confirmed_date = fields.Date(string="Confirmed Delivery Date")
    ready_to_ship_date = fields.Date(string="Ready To Ship Date")
    shipment_date = fields.Date(string="Shipment Date", help="Date on which picking is created at supplier")
    arrival_date = fields.Date(string="Arrival date in the country", help="Date of the arrival of the goods at custom")
    receipt_date = fields.Date(string="Receipt Date", compute="_get_receipt_date", readonly=True, help="for a PO, date of the first godd receipt.")
    confirmed_date_by_synchro = fields.Boolean(string="Confirmed Date by Synchro", default=False)
    transport_type = fields.Selection(string="Transport Mode",
                                      selection=[('', ''), ('express', 'Express'), ('hand', 'Hand carry'),
                                                 ('sea', 'Sea'), ('air', 'Air'), ('road', 'Road')],
                                      help="Number of days this field has to be associated with a transport mode selection")
    est_transport_lead_time = fields.Float(string="Est. Transport Lead Time", digits=(16, 2),
                                           help="Estimated Transport Lead-Time in weeks")
    partner_type = fields.Selection(string="Partner Type",
                                    selection=[('internal', 'Internal'), ('section', 'Inter-section'),
                                               ('external', 'External'), ('esc', 'ESC'),
                                               ('intermission', 'Intermission')], readonly=True)
    internal_type = fields.Selection(string="Type",
                                     selection=[('national', 'National'), ('international', 'International')], readonly=True)
    # analytic_distribution_id = fields.Many2one(string="Analytic Distribution", comodel_name="analytic.distribution",
    #                                            ondelete="set null", index=True)
    # commitment_ids = fields.One2many(string="Commitment Vouchers", comodel_name="account.commitment",
    #                                  inverse_name="purchase_id", readonly=True)
    has_confirmed_line = fields.Boolean(string="Has a confirmed line", compute="_get_fake",
                                        search="_search_has_confirmed_line", readonly=True,
                                        help="Only used to SEARCH for POs with at least one line in Confirmed state")
    has_confirmed_or_further_line = fields.Boolean(string="Has a confirmed (or further) line", compute="_get_fake",
                                                   search="_search_has_confirmed_or_further_line", readonly=True,
                                                   help="Only used to SEARCH for POs with at least one line in Confirmed or Closed state")
    split_during_sll_mig = fields.Boolean(string="PO split at Coordo during SLL migration", default=False)
    empty_po_cancelled = fields.Boolean(string="Empty PO cancelled",
                                        help="Flag to see if the PO has been cancelled while empty", default=False)
    from_address = fields.Many2one(string="From Address", comodel_name="res.partner.address", ondelete="restrict",
                                   required=True, default=lambda self: self.env.company.partner_id.address_get(['default'])['default'])
    msg_big_qty = fields.Char(string="Lines with 10 digits total amounts", compute="_get_msg_big_qty", readonly=True)
    show_default_msg = fields.Boolean(string="Show PO Default Message", default=False)
    not_beyond_validated = fields.Boolean(string="Check if lines' and document's state is not beyond validated",
                                          compute="_get_not_beyond_validated", readonly=True, default=True)
    po_version = fields.Integer(string="Migration: manage old flows",
                                help="v1: dpo reception not synced up, SI/CV generated at PO confirmation", default=2)
    merged_po = fields.Boolean(string="PO is merged", readonly=True, default=False)
    nb_creation_message_nr = fields.Integer(string="Number of NR creation messages",
                                            compute="_get_nb_creation_message_nr", readonly=True)
    ad_lines_message_nr = fields.Char(string="Line number of NR message for missing AD",
                                      compute="_get_ad_lines_message_nr", size=1024, readonly=True)
    ad_lines_missing_message = fields.Char(string="Line number of lines missing AD",
                                           compute="_get_ad_lines_missing_message", size=1024, readonly=True)
    # tax_line = fields.One2many(string="Tax Lines", comodel_name="account.invoice.tax", inverse_name="purchase_id")
    alert_msl_mml = fields.Char(string="Contains non-conform MML/MSL", compute="_get_header_msl_mml_alert", readonly=True)
    catalogue_ratio_conform = fields.Integer(string="PO Lines Adherence", compute="_get_catalogue_ratio", readonly=True)
    catalogue_ratio_not_conform = fields.Integer(string="PO Lines Mismatch", compute="_get_catalogue_ratio", readonly=True)
    catalogue_ratio_no_catalogue = fields.Integer(string="Not in Catalogue", compute="_get_catalogue_ratio", readonly=True)
    catalogue_ratio_text = fields.Char(string="Catalogue Ratio", compute="_get_catalogue_ratio", readonly=True)
    catalogue_ratio_plain_text = fields.Char(string="Catalogue Ratio", compute="_get_catalogue_ratio", readonly=True)
    catalogue_total_price_deviation = fields.Char(string="PO Total Price Deviation", compute="_get_catalogue_ratio", size=16, readonly=True)
    catalogue_deviation_text = fields.Char(string="PO Deviation", compute="_get_catalogue_ratio", readonly=True)
    catalogue_deviation_plain_text = fields.Char(string="PO Deviation", compute="_get_catalogue_ratio", readonly=True)
    catalogue_exists = fields.Boolean(string="Has a valid catalogue", compute="_get_catalogue_ratio", readonly=True)
    catalogue_display_tab = fields.Boolean(string="Display tab catalogue", compute="_get_catalogue_ratio", readonly=True)
    catalogue_exists_text = fields.Char(string="Catalogue Lines Status", compute="_get_catalogue_ratio", readonly=True)
    catalogue_description_text = fields.Char(string="Catalogue Text", compute="_get_catalogue_description_text", readonly=True)
    # catalogue_id = fields.Many2one(string="Catalogue", compute="_get_catalogue_description_text",
    #                                comodel_name="supplier.catalogue", ondelete="set null", readonly=True)
    catalogue_not_applicable = fields.Boolean(string="PO confirmed before pol catalogue", readonly=True, default=False)
    sequence_id = fields.Many2one(string="Lines Sequence", comodel_name="ir.sequence", ondelete="restrict",
                                  required=True, help="This field contains the information related to the numbering of the lines of this order.")
    # down_payment_ids = fields.One2many(string="Down Payments", comodel_name="account.move.line",
    #                                    inverse_name="down_payment_id", readonly=True)
    down_payment_filter = fields.Many2one(string="PO for Down Payment", compute="_get_fake", search="_search_po_for_down_payment",
                                          comodel_name="purchase.order", ondelete="set null", readonly=True)
    # currency_id = fields.Many2one(string="Currency", related="pricelist_id.currency_id", comodel_name="res.currency",
    #                               ondelete="set null", readonly=True)
    functional_amount_untaxed = fields.Float(string="Functional Untaxed Amount", compute="_amount_currency",
                                             digits=(16, 2), readonly=True)
    functional_amount_tax = fields.Float(string="Functional Taxes", compute="_amount_currency", digits=(16, 2), readonly=True)
    functional_amount_total = fields.Float(string="Functional Total", compute="_amount_currency", digits=(16, 2), readonly=True)
    functional_currency_id = fields.Many2one(string="Functional Currency", related="company_id.currency_id",
                                             comodel_name="res.currency", ondelete="set null", readonly=True)
    customer_id = fields.Many2one(string="Customer", comodel_name="res.partner", ondelete="set null",
                                  domain="[('customer', '=', True)]")
    # unique_fo_id = fields.Many2one(string="Unique FO", comodel_name="sale.order", ondelete="set null", readonly=True,
    #                                help="This field is used to have only one PO for a specific FO/IR if the supplier 'Order creation method' is set to 'Requirements by Order'.")
    unique_rule_type = fields.Char(string="Unique Replenishment rule type", size=128, readonly=True,
                                   help="This field is used to have only one PO by replenishmentrules if the supplier 'Order creation method' is set to 'Requirements by Order.'")
    po_from_rr = fields.Boolean(string="PO from replenishment rules", readonly=True, default=False)
    # related_sourcing_id = fields.Many2one(string="Sourcing group", comodel_name="related.sourcing", ondelete="set null", readonly=True)
    # tender_id = fields.Many2one(string="Tender", comodel_name="tender", ondelete="set null", readonly=True)
    rfq_delivery_address = fields.Many2one(string="Delivery address", comodel_name="res.partner.address", ondelete="set null")
    # origin_tender_id = fields.Many2one(string="Tender", comodel_name="tender", ondelete="set null", readonly=True)
    from_procurement = fields.Boolean(string="RfQ created by a procurement order")
    rfq_ok = fields.Boolean(string="Is RfQ ?", default=lambda self: self.env.context.get('rfq_ok', False), )
    valid_till = fields.Date(string="Valid Till")
    # sale_order_id = fields.Many2one(string="Link between RfQ and FO", comodel_name="sale.order", ondelete="set null", readonly=True)
    sended_by_supplier = fields.Boolean(string="Sended by supplier", readonly=True, default=True)
    push_fo = fields.Boolean(string="The Push FO case", default=False)
    from_sync = fields.Boolean(string="Updated by synchronization")
    fo_sync_date = fields.Datetime(string="FO sync. date", readonly=True)
    is_validated_and_synced = fields.Boolean(string="Validated and Synced", compute="_is_validated_and_synced", readonly=True, default=False)
    # allocation_report_lines = fields.One2many(string="Allocation lines",
    #                                           comodel_name="purchase.order.line.allocation.report", inverse_name="order_id")
    display_intl_transport_ok = fields.Boolean(string="Displayed intl transport", default=lambda *a: False, )
    intl_supplier_ok = fields.Boolean(string="International Supplier", default=lambda *a: False, )
    transport_cost = fields.Float(string="Transport cost", digits=(16, 2))
    transport_currency_id = fields.Many2one(string="Currency", comodel_name="res.currency", ondelete="set null")
    total_price_include_transport = fields.Float(string="Total incl. transport", compute="_get_include_transport",
                                                 digits=(16, 2), readonly=True)
    func_total_price_include_transport = fields.Float(string="Functionnal total incl. transport",
                                                      compute="_get_include_transport", digits=(16, 2), readonly=True)
    # incoterm_id = fields.Many2one(string="Incoterm", comodel_name="stock.incoterms", ondelete="set null")
    transport_order_id = fields.Many2one(string="Linked Purchase Order", comodel_name="purchase.order",
                                         ondelete="set null", domain="[('categ', '!=', 'transport')]")
    # picking_transport_ids = fields.One2many(string="Linked deliveries", comodel_name="stock.picking", inverse_name="transport_order_id")
    # shipment_transport_ids = fields.One2many(string="Linked shipments", comodel_name="shipment", inverse_name="transport_order_id")
    # transport_customs_fees_ids = fields.One2many(string="Inbound/Outbound Transport Orders for Customs Fees",
    #                                              compute="_get_transport_docs_customs",
    #                                              comodel_name="transport.order.customs.fees", readonly=True)
    # transport_transport_fees_ids = fields.One2many(string="Inbound/Outbound Transport Orders for Transport Fees",
    #                                                compute="_get_transport_docs_transport",
    #                                                comodel_name="transport.order.transport.fees", readonly=True)
    transport_active = fields.Boolean(string="Transport Management active", compute="get_transport_active", readonly=True)
    tax_identification_number = fields.Char(string="Supplier TIN", related="partner_id.tax_identification_number",
                                            size=15, readonly=True)
    business_registration_number = fields.Char(string="Supplier RCCM",
                                               related="partner_id.business_registration_number", size=15, readonly=True)
    cross_docking_ok = fields.Boolean(string="Cross docking", default=False)
    import_in_progress = fields.Boolean(string="Import in progress", compute="_get_import_progress", readonly=True, default=lambda *a: False)
    # import_filenames = fields.One2many(string="Imported files", comodel_name="purchase.order.simu.import.file",
    #                                    inverse_name="order_id", readonly=True)
    auto_exported_ok = fields.Boolean(string="PO exported to ESC")
    can_be_auto_exported = fields.Boolean(string="Can be auto exported ?", compute="_can_be_auto_exported", readonly=True)

    # Compute methods
    def _get_allocation_setup(self):
        """"""
        for record in self:
            record.allocation_setup = ""

    def _get_short_partner_ref(self):
        """"""
        for record in self:
            record.short_partner_ref = ""

    def _get_fake(self):
        """"""
        for record in self:
            record.product_id = None
            record.has_confirmed_line = False
            record.has_confirmed_or_further_line = False
            record.down_payment_filter = None

    def _get_no_line(self):
        """"""
        for record in self:
            record.no_line = False

    def _po_from_x(self):
        """"""
        for record in self:
            record.po_from_ir = False
            record.po_from_fo = False

    def _get_project_ref(self):
        """"""
        for record in self:
            record.fnct_project_ref = ""
            record.sourced_references = ""

    def _get_dest_partner_names(self):
        """"""
        for record in self:
            record.dest_partner_names = ""

    def _get_vat_ok(self):
        """"""
        for record in self:
            record.vat_ok = False

    def _get_requested_date_in_past(self):
        """"""
        for record in self:
            record.requested_date_in_past = False

    def _get_customer_ref(self):
        """"""
        for record in self:
            record.customer_ref = ""

    def _get_short_customer_ref(self):
        """"""
        for record in self:
            record.short_customer_ref = ""

    def _get_line_count(self):
        """"""
        for record in self:
            record.line_count = 0

    def _get_location_data(self):
        """"""
        for record in self:
            # record.location_ids = None
            record.location_names = ""

    # @api.depends('empty_po_cancelled', 'order_line.state')
    @api.depends('empty_po_cancelled')
    def _get_less_advanced_line_state(self):
        """
        Get the less advanced state of the purchase order lines
        Used to compute PO and RfQ state
        """
        for record in self:
            record.state = ""
            record.rfq_state = ""

    def _shipped_rate(self):
        """"""
        for record in self:
            record.shipped_rate = 0.0

    def _invoiced(self):
        """"""
        for record in self:
            record.invoiced = False

    def _invoiced_rate(self):
        """"""
        for record in self:
            record.invoiced_rate = 0.0

    # @api.depends('order_line.date_planned')
    def _minimum_planned_date(self):
        """"""
        for record in self:
            record.minimum_planned_date = None

    # @api.depends('order_line.price_subtotal', 'order_line.taxes_id', 'order_line.price_unit', 'order_line.product_qty',
    #              'order_line.product_id')
    # Also depends on _get_order_state_changed and _get_order_from_corner_tax
    def _amount_all(self):
        """"""
        for record in self:
            record.has_tax_at_line_level = False
            record.amount_untaxed = 0.0
            record.amount_tax = 0.0
            record.amount_total = 0.0
            record.amount_total_tender_currency = 0.0

    # @api.depends('order_line')
    def _is_fixed_type(self):
        """
        For each PO, set is the Order Type of the PO can be changed or not
        """
        for record in self:
            record.fixed_order_type = ""

    def _get_receipt_date(self):
        """
        Returns the date of the first picking for the PO
        """
        # pick_obj = self.env['stock.picking']
        for po in self:
            # pick_ids = pick_obj.search([('purchase_id', '=', order.id)], offset=0, limit=1, order='date_done')
            # po.receipt_date = pick_ids and pick_ids[0].date_done or False
            po.receipt_date = False

    def _get_msg_big_qty(self):
        """"""
        for record in self:
            record.msg_big_qty = ""

    def _get_not_beyond_validated(self):
        """"""
        for record in self:
            record.not_beyond_validated = False

    def _get_nb_creation_message_nr(self):
        """"""
        for record in self:
            record.nb_creation_message_nr = 0

    def _get_ad_lines_message_nr(self):
        """"""
        for record in self:
            record.ad_lines_message_nr = ""

    def _get_ad_lines_missing_message(self):
        """"""
        for record in self:
            record.ad_lines_missing_message = ""

    def _get_header_msl_mml_alert(self):
        """"""
        for record in self:
            record.alert_msl_mml = ""

    def _get_catalogue_ratio(self):
        """"""
        for record in self:
            record.catalogue_ratio_conform = 0
            record.catalogue_ratio_not_conform = 0
            record.catalogue_ratio_no_catalogue = 0
            record.catalogue_ratio_text = ""
            record.catalogue_ratio_plain_text = ""
            record.catalogue_total_price_deviation = ""
            record.catalogue_deviation_text = ""
            record.catalogue_deviation_plain_text = ""
            record.catalogue_exists = False
            record.catalogue_display_tab = False
            record.catalogue_exists_text = ""

    def _get_catalogue_description_text(self):
        """"""
        for record in self:
            record.catalogue_description_text = ""
            # record.catalogue_id = None

    def _amount_currency(self):
        """"""
        for record in self:
            record.functional_amount_untaxed = 0.0
            record.functional_amount_tax = 0.0
            record.functional_amount_total = 0.0

    def _is_validated_and_synced(self):
        """"""
        for record in self:
            record.is_validated_and_synced = False

    def _get_include_transport(self):
        """"""
        for record in self:
            record.total_price_include_transport = 0.0
            record.func_total_price_include_transport = 0.0

    def _get_transport_docs_customs(self):
        """"""
        for record in self:
            record.transport_customs_fees_ids = None

    def _get_transport_docs_transport(self):
        """"""
        for record in self:
            record.transport_transport_fees_ids = None

    def get_transport_active(self):
        """"""
        for record in self:
            record.transport_active = False

    def _get_import_progress(self):
        """"""
        for record in self:
            record.import_in_progress = False

    def _can_be_auto_exported(self):
        """"""
        for record in self:
            record.can_be_auto_exported = False

    # Search methods
    def _search_has_confirmed_line(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _search_has_confirmed_or_further_line(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _src_customer_ref(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _search_po_for_down_payment(self, operator, value):
        """"""
        return [('id', operator, value)]

    # Inverse methods
    def _set_minimum_planned_date(self):
        """"""
        pass
