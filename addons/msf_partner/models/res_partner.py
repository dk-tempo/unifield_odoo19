from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    # Default methods
    def _default_supplier(self):
        """"""
        return False

    def _default_customer(self):
        """"""
        return False

    def _default_category(self):
        """"""
        return None

    def _get_instance_creator(self):
        if 'sync_update_execution' not in self.env.context:
            entity_obj = self.env.get('sync.client.entity')
            if entity_obj:
                return entity_obj.get_entity().name
        return False

    # Selection methods
    def _lang_get(self):
        """"""
        return [('option_a', 'Option A'), ('option_b', 'Option B')]

    name = fields.Char(string="Name", size=128, required=True)
    legal_name = fields.Char(string="Legal Name", size=128)
    date = fields.Date(string="Date")
    title = fields.Many2one(string="Partner Form", comodel_name="res.partner.title")
    parent_id = fields.Many2one(string="Parent Partner", comodel_name="res.partner")
    child_ids = fields.One2many(string="Partner Ref.", comodel_name="res.partner", inverse_name="parent_id")
    ref = fields.Char(string="Reference", size=64)
    lang = fields.Selection(string="Language", selection=_lang_get,
                            help="If the selected language is loaded in the system, all documents related to this partner will be printed in this language. If not, it will be english.")
    user_id = fields.Many2one(string="Salesman", comodel_name="res.users",
                              help="The internal user that is in charge of communicating with this partner if any.")
    vat = fields.Char(string="VAT", size=32,
                      help="Value Added Tax number. Check the box if the partner is subjected to the VAT. Used by the VAT legal statement.")
    bank_ids = fields.One2many(string="Banks", comodel_name="res.partner.bank", inverse_name="partner_id")
    website = fields.Char(string="Website", size=64, help="Website of Partner")
    comment = fields.Text(string="Notes")
    address = fields.One2many(string="Contacts", comodel_name="res.partner.address", inverse_name="partner_id")
    category_id = fields.Many2many(string="Categories", comodel_name="res.partner.category",
                                   relation="res_partner_category_rel", column1="partner_id", column2="category_id",
                                   default=_default_category)
    # events = fields.One2many(string="Events", comodel_name="res.partner.event", inverse_name="partner_id")
    credit_limit = fields.Float(string="Credit Limit")
    ean13 = fields.Char(string="EAN13", size=13)
    active = fields.Boolean(string="Active", default=1, )
    state = fields.Selection(string="Partner Status",
                             selection=[('active', 'Active'), ('phase_out', 'Phase Out'), ('inactive', 'Inactive')],
                             readonly=True, default="active")
    customer = fields.Boolean(string="Customer", help="Check this box if the partner is a customer.",
                              default=_default_customer)
    supplier = fields.Boolean(string="Supplier",
                              help="Check this box if the partner is a supplier. If it's not checked, purchase people will not see it when encoding a purchase order.",
                              default=_default_supplier)
    city = fields.Char(string="City", related="address.city")
    phone = fields.Char(string="Phone", related="address.phone")
    mobile = fields.Char(string="Mobile", related="address.mobile")
    country = fields.Many2one(string="Country", related="address.country_id", comodel_name="res.country")
    employee = fields.Boolean(string="Employee", help="Check this box if the partner is an Employee.")
    email = fields.Char(string="E-mail", related="address.email", size=240)
    company_id = fields.Many2one(string="Company", comodel_name="res.company",
                                 default=lambda self: self.env.company)
    tax_identification_number = fields.Char(string='Tax Identification Number', size=15, help="Tax Identification Number")
    business_registration_number = fields.Char(string='Business Registration Number', size=15, help="Business Registration Number")
    # property_product_pricelist = fields.Many2one(string="Field orders default currency",
    #                                              comodel_name="product.pricelist",
    #                                              help="This currency will be used, instead of the default one, for field orders to the current partner",
    #                                              domain="[('type', '=', 'sale')]",
    #                                              default=lambda self, cr, uid, c: self.pool.get(
    #                                                  'product.pricelist').get_company_default_pricelist(cr, uid, 'sale',
    #                                                                                                     c), )
    credit = fields.Float(string="Total Receivable", compute="_credit_debit_get", search="_credit_search",
                          digits=(16, 2), readonly=True, help="Total amount this customer owes you.")
    debit = fields.Float(string="Total Payable", compute="_credit_debit_get", search="_debit_search", digits=(16, 2),
                         readonly=True, help="Total amount you have to pay to this supplier.")
    debit_limit = fields.Float(string="Payable Limit")
    # property_account_payable = fields.Many2one(string="Account Payable", comodel_name="account.account",
    #                                            help="This account will be used instead of the default one as the payable account for the current partner",
    #                                            domain="[('type', '!=', 'view'), ('type', 'in', ['payable', 'other']), ('user_type_code', 'in', ['payables', 'tax', 'cash']), ('type_for_register', '!=', 'donation')]")
    # property_account_receivable = fields.Many2one(string="Account Receivable", comodel_name="account.account",
    #                                               help="This account will be used instead of the default one as the receivable account for the current partner",
    #                                               domain="[('type', '!=', 'view'), '|', ('type', '=', 'receivable'), '&', ('type', '=', 'other'), ('user_type_code', '=', 'cash')]")
    # property_account_position = fields.Many2one(string="Fiscal Position", comodel_name="account.fiscal.position",
    #                                             help="The fiscal position will determine taxes and the accounts used for the partner.")
    # property_payment_term = fields.Many2one(string="Payment Term", comodel_name="account.payment.term",
    #                                         help="This payment term will be used instead of the default one for the current partner")
    ref_companies = fields.One2many(string="Companies that refers to partner", comodel_name="res.company",
                                    inverse_name="partner_id")
    last_reconciliation_date = fields.Datetime(string="Latest Reconciliation Date",
                                               help="Date on which the partner accounting entries were reconciled last time")
    # invoice_ids = fields.One2many(string="Invoices", comodel_name="account.invoice.line", inverse_name="partner_id",
    #                               readonly=True)
    # contract_ids = fields.One2many(string="Contracts", comodel_name="account.analytic.account",
    #                                inverse_name="partner_id", readonly=True)
    # property_stock_customer = fields.Many2one(string="Customer Location", comodel_name="stock.location", required=True,
    #                                           help="This stock location will be used, instead of the default one, as the destination location for goods you send to this partner.")
    # property_stock_supplier = fields.Many2one(string="Supplier Location", comodel_name="stock.location", required=True,
    #                                           help="This stock location will be used, instead of the default one, as the source location for goods you receive from the current partner.")
    # donation_payable_account = fields.Many2one(string="Donation Payable Account", comodel_name="account.account",
    #                                            domain="[('type', '!=', 'view'), ('type', '=', 'payable'), ('user_type_code', '=', 'payables'), ('type_for_register', '=', 'donation')]")
    by_invoice_type = fields.Boolean(readonly=True, compute="_get_fake", search="_get_search_by_invoice_type")
    check_partner_so = fields.Boolean(string="Check Partner Type On SO", compute="_get_fake",
                                      search="_check_partner_type_so", readonly=True)
    partner_not_int = fields.Boolean(string="Is PO/Tender from FO ?", compute="_get_fake",
                                     search="_search_partner_not_int", readonly=True)
    # property_product_pricelist_purchase = fields.Many2one(string="Purchase default currency",
    #                                                       comodel_name="product.pricelist",
    #                                                       help="This currency will be used, instead of the default one, for purchases from the current partner",
    #                                                       domain="[('type', '=', 'purchase')]",
    #                                                       default=lambda self, cr, uid, c: self.pool.get(
    #                                                           'product.pricelist').get_company_default_pricelist(cr,
    #                                                                                                              uid,
    #                                                                                                              'purchase',
    #                                                                                                              c), )
    zone = fields.Selection(string="Zone", selection=[('national', 'National'), ('international', 'International')],
                            required=True, default="national")
    customer_lt = fields.Integer(string="Customer Lead Time", default=0)
    supplier_lt = fields.Integer(string="Supplier Lead Time", default=0)
    procurement_lt = fields.Integer(string="Internal Lead Time", default=0)
    transport_0_lt = fields.Integer(string="1st Transport Lead Time", default=0)
    transport_0 = fields.Selection(string="1st (favorite) Mode of Transport",
                                   selection=[('', ''), ('express', 'Express'), ('hand', 'Hand carry'), ('sea', 'Sea'),
                                              ('air', 'Air'), ('road', 'Road')], default="")
    transport_1_lt = fields.Integer(string="2nd Transport Lead Time", default=0)
    transport_1 = fields.Selection(string="2nd Mode of Transport",
                                   selection=[('', ''), ('express', 'Express'), ('hand', 'Hand carry'), ('sea', 'Sea'),
                                              ('air', 'Air'), ('road', 'Road')], default="")
    transport_2_lt = fields.Integer(string="3rd Transport Lead Time", default=0)
    transport_2 = fields.Selection(string="3nd Mode of Transport",
                                   selection=[('', ''), ('express', 'Express'), ('hand', 'Hand carry'), ('sea', 'Sea'),
                                              ('air', 'Air'), ('road', 'Road')], default="")
    default_delay = fields.Integer(string="Supplier Lead Time (computed)", compute="_calc_dellay", readonly=True)
    po_by_project = fields.Selection(string="Order creation mode",
                                     selection=[('all', 'All requirements'), ('project', 'Requirements by Project'),
                                                ('category', 'Requirements by Category'),
                                                ('category_project', 'Requirements by Category and Project'),
                                                ('isolated', 'Requirements by Order')],
                                     help="When option “All requirements” is set for a given supplier, the system will create a PO that merge all requirements for this supplier. If option “Requirements by Project” is set, the POs will be created by original requestor (customer of the SO origin), meaning system creates one PO by project for this supplier. If option 'Requirements by Category' is set, the system will create a PO that merge all requirements by category for this supplier. If option 'Requirements by Category and Project' is set, the system will create a PO that merge only the requirements of one customer and one category. If option 'Requirements by Order' is set, the system will create a PO that merge lines coming from the same FO/IR.",
                                     default='all', )
    manufacturer = fields.Boolean(string="Manufacturer", help="Check this box if the partner is a manufacturer",
                                  default=False, )
    partner_type = fields.Selection(string="Partner type",
                                    selection=[('internal', 'Internal'), ('section', 'Inter-section'),
                                               ('external', 'External'), ('esc', 'ESC'),
                                               ('intermission', 'Intermission')], required=True,
                                    default='external', )
    split_po = fields.Selection(string="Split PO ?", selection=[('yes', 'Yes'), ('no', 'No')],
                                default=False, )
    in_product = fields.Boolean(string="In product", compute="_set_in_product", search="search_in_product",
                                readonly=True)
    min_qty = fields.Char(string="Min. Qty", compute="_set_in_product", readonly=True)
    delay = fields.Char(string="Delivery Lead time", compute="_set_in_product", readonly=True)
    supplier_ranking = fields.Selection(string="Ranking", compute="_set_in_product",
                                        selection=[('1', '1st choice'), ('2', '2nd choice'), ('3', '3rd choice'),
                                                   ('4', '4th choice'), ('5', '5th choice'), ('6', '6th choice'),
                                                   ('7', '7th choice'), ('8', '8th choice'), ('9', '9th choice'),
                                                   ('10', '10th choice'), ('11', '11th choice'), ('12', '12th choice'),
                                                   ('13', '-99'), ('14', '0'), ('15', '1'), ('16', '2'), ('17', '3'), ('18', '4')],
                                        readonly=True)
    price_unit = fields.Float(string="Unit price", compute="_get_price_info", digits=(16, 2), readonly=True)
    valide_until_date = fields.Char(string="Valid until date", compute="_get_price_info", readonly=True)
    price_currency = fields.Many2one(string="Currency", compute="_get_price_info", comodel_name="res.currency",
                                     readonly=True)
    vat_ok = fields.Boolean(string="VAT OK", compute="_get_vat_ok", readonly=True, default=True)
                            # default=lambda obj, cr, uid, c: obj.pool.get('unifield.setup.configuration').get_config(cr,
                            #                                                                                         uid).vat_ok, )
    is_instance = fields.Boolean(string="Is current instance partner id", compute="_get_is_instance",
                                 search="_get_is_instance_search", readonly=True)
    transporter = fields.Boolean(string="Transporter", default=False)
    is_coordo = fields.Boolean(string="Is a coordination ?", compute="_get_is_coordo", search="_get_is_coordo_search",
                               readonly=True)
    locally_created = fields.Boolean(string="Locally Created", readonly=True, help="Partner Created on this instance",
                                     default=True)
    allow_external_edition = fields.Boolean(string="Editable ext. partner", compute="_get_allow_external_edition",
                                            search="_search_allow_external_edition", readonly=True, default=True)
    instance_creator = fields.Char(string="Instance Creator", size=64, readonly=True,
                                   default=_get_instance_creator)
    # catalogue_ids = fields.One2many(string="Catalogues", comodel_name="supplier.catalogue", inverse_name="partner_id",
    #                                 readonly=True)
    catalogue_bool = fields.Char(string="Catalogue", compute="_get_bool_cat", readonly=True)
    leadtime = fields.Integer(string="Lead Time", default=2, )
    filter_for_third_party = fields.Char(string="Internal Field to filter partner on finance entries", compute="_get_fake", search="_search_fake",
                                         readonly=True)
    filter_for_third_party_in_advance_return = fields.Char(string="Internal Field to filter partner on advance return", compute="_get_fake",
                                                           search="_search_filter_third", readonly=True)
    available_for_dpo = fields.Boolean(string="Available for DPO (used on FO line)", compute="_get_available_for_dpo",
                                       search="_src_available_for_dpo", readonly=True)
    available_on_po_dpo = fields.Boolean(string="Available as destination partner on DPO", compute="_get_fake",
                                         search="_search_available_on_po_dpo", readonly=True)
    check_partner = fields.Boolean(string="Check Partner Type", compute="_get_fake", search="_check_partner_type",
                                   readonly=True)
    check_partner_rfq = fields.Boolean(string="Check Partner Type on RFQ", compute="_get_fake",
                                       search="_check_partner_type_rfq", readonly=True)
    check_partner_ir = fields.Boolean(string="Check Partner Type On IR", compute="_get_fake",
                                      search="_check_partner_type_ir", readonly=True)
    check_partner_po = fields.Boolean(string="Check Partner Type On PO", compute="_get_fake",
                                      search="_check_partner_type_po", readonly=True)
    line_contains_fo = fields.Boolean(string="Lines contains FO", compute="_get_fake", search="_src_contains_fo",
                                      readonly=True)
    is_rfq_generated = fields.Boolean(string="RfQ Generated for the tender in context", compute="_get_is_rfq_generated",
                                      readonly=True)
    # claim_ids_res_partner = fields.One2many(string="Claims", comodel_name="return.claim",
    #                                         inverse_name="partner_id_return_claim")

    # Compute methods
    def _credit_debit_get(self):
        """"""
        for record in self:
            record.credit = 0.0
            record.debit = 0.0

    def _get_fake(self):
        """"""
        for record in self:
            record.by_invoice_type = False
            record.check_partner_so = False
            record.partner_not_int = False
            record.filter_for_third_party = ""
            record.filter_for_third_party_in_advance_return = ""
            record.available_on_po_dpo = False
            record.check_partner = False
            record.check_partner_rfq = False
            record.check_partner_ir = False
            record.check_partner_po = False
            record.line_contains_fo = False

    def _calc_dellay(self):
        """"""
        for record in self:
            record.default_delay = 0

    def _set_in_product(self):
        """"""
        for record in self:
            record.in_product = False
            record.min_qty = ""
            record.delay = ""
            record.supplier_ranking = ""

    def _get_price_info(self):
        """"""
        for record in self:
            record.price_unit = 0.0
            record.valide_until_date = ""
            record.price_currency = None

    def _get_vat_ok(self):
        """"""
        for record in self:
            record.vat_ok = False

    def _get_is_instance(self):
        """"""
        for record in self:
            record.is_instance = False

    def _get_is_coordo(self):
        """"""
        for record in self:
            record.is_coordo = False

    def _get_allow_external_edition(self):
        """"""
        for record in self:
            record.allow_external_edition = False

    def _get_bool_cat(self):
        """"""
        for record in self:
            record.catalogue_bool = ""

    def _get_available_for_dpo(self):
        """"""
        for record in self:
            record.available_for_dpo = False

    def _get_is_rfq_generated(self):
        """"""
        for record in self:
            record.is_rfq_generated = False

    # Search methods
    def _check_partner_type_so(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _debit_search(self, operator, value):
        """"""
        return [('id', operator, value)]

    def search_in_product(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _check_partner_type_ir(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _search_available_on_po_dpo(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _src_contains_fo(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _check_partner_type(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _search_partner_not_int(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _check_partner_type_po(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _get_search_by_invoice_type(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _credit_search(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _search_fake(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _src_available_for_dpo(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _get_is_coordo_search(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _get_is_instance_search(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _search_filter_third(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _search_allow_external_edition(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _check_partner_type_rfq(self, operator, value):
        """"""
        return [('id', operator, value)]


