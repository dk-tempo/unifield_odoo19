from odoo import api, fields, models


class ProductTemplate(models.Model):
    _name = "product.template"
    _description = "Product Template"

    # Default methods
    def _get_uom_id(self):
        """"""
        return self.env.ref("msf_uom.product_uom_unit")

    def _default_category(self):
        """"""
        return None

    def _get_valid_stat(self):
        """"""
        return None


    name = fields.Char(string="Description", translate=True, size=128, required=True)
    product_manager = fields.Many2one(string="Product Manager", comodel_name="res.users",
                                      help="This is use as task responsible")
    description = fields.Text(string="Description", translate=True)
    description_purchase = fields.Text(string="Purchase Description", translate=True)
    description_sale = fields.Text(string="Sale Description", translate=True)
    type = fields.Selection(string="Product Type",
                            selection=[('product', 'Stockable Product'), ('consu', 'Non-Stockable'),
                                       ('service_recep', 'Service with Reception')], required=True,
                            help="Will change the way procurements are processed. Consumables are stockable products with infinite stock, or for use when you have no inventory management in the system.",
                            default="product")
    supply_method = fields.Selection(string="Supply method", selection=[('produce', 'Produce'), ('buy', 'Buy')],
                                     required=True,
                                     help="Produce will generate production order or tasks, according to the product type. Purchase will trigger purchase orders when requested.",
                                     default='buy')
    sale_delay = fields.Float(string="Customer Lead Time",
                              help="This is the average delay in days between the confirmation of the customer order and the delivery of the finished products. It's the time you promise to your customers.",
                              default=0)
    produce_delay = fields.Float(string="Manufacturing Lead Time",
                                 help="Average delay in days to produce this product. This is only for the production order and, if it is a multi-level bill of material, it's only for the level of this product. Different lead times will be summed for all levels and purchase orders.",
                                 default=0)
    procure_method = fields.Selection(string="Procurement Method", selection=[('make_to_stock', 'Make to Stock'),
                                                                              ('make_to_order', 'Make to Order')],
                                      required=True,
                                      help="'Make to Stock': When needed, take from the stock or wait until re-supplying. 'Make to Order': When needed, purchase or produce for the procurement request.",
                                      default='make_to_stock')
    rental = fields.Boolean(string="Can be Rent")
    # categ_id = fields.Many2one(string="Category", comodel_name="product.category", required=True,
    #                            help="Select category for the current product", domain="[('type','=','normal')]",
    #                            default=_default_category)
    standard_price = fields.Monetary(string="Cost Price", required=True,
                                  help="Price of product calculated according to the selected costing method.",
                                  default=1, currency_field="currency_id")
    currency_id = fields.Many2one(string="Currency", comodel_name="res.currency", readonly=True,
                                  default=lambda self: self.env.company.currency_id)
    finance_price = fields.Monetary(string="Finance Cost Price", readonly=True, currency_field="finance_price_currency_id")
    finance_price_currency_id = fields.Many2one(readonly=True, compute="_get_finance_price_currency_id",
                                                comodel_name="res.currency")
    list_price = fields.Monetary(string="Sale Price", compute="_get_list_price", store=True, readonly=True,
                              help="Base price for computing the customer price. Sometimes called the catalog price.",
                              default=1, currency_field="field_currency_id")
    field_currency_id = fields.Many2one(string="Currency", comodel_name="res.currency", readonly=True,
                                        default=lambda self: self.env.company.currency_id)
    volume = fields.Float(string="Volume", digits=(16, 5), help="The volume in dm3.")
    volume_updated = fields.Boolean(string="Volume updated (deprecated)", readonly=True, default=False)
    weight = fields.Float(string="Gross weight", digits=(16, 5), help="The gross weight in Kg.")
    weight_net = fields.Float(string="Net weight", digits=(16, 5), help="The net weight in Kg.")
    cost_method = fields.Selection(string="Costing Method",
                                   selection=[('average', 'Average Price'), ('standard', 'Standard Price')],
                                   required=True,
                                   help="Average Price: the cost price is recomputed at each reception of products.",
                                   default='average')
    warranty = fields.Float(string="Warranty (months)")
    sale_ok = fields.Boolean(string="Can be Sold",
                             help="Determines if the product can be visible in the list of product within a selection from a sale order line.",
                             default=1)
    purchase_ok = fields.Boolean(string="Can be Purchased",
                                 help="Determine if the product is visible in the list of products within a selection from a purchase order line.",
                                 default=1)
    # state = fields.Many2one(string="UniField Status", comodel_name="product.status", required=True,
    #                         help="Tells the user if he can use the product or not.", default=_get_valid_stat)
    uom_id = fields.Many2one(string="Default Unit Of Measure", comodel_name="uom.uom", required=True,
                             help="Default Unit of Measure used for all stock operation.", default=_get_uom_id)
    uom_po_id = fields.Many2one(string="Purchase Unit of Measure", comodel_name="uom.uom", required=True,
                                help="Default Unit of Measure used for purchase orders. It must be in the same category than the default unit of measure.",
                                default=_get_uom_id)
    uos_id = fields.Many2one(string="Unit of Sale", comodel_name="uom.uom",
                             help="Used by companies that manage two units of measure: invoicing and inventory management. For example, in food industries, you will manage a stock of ham but invoice in Kg. Keep empty to use the default UOM.")
    uos_coeff = fields.Float(string="UOM -> UOS Coeff", digits=(16, 4),
                             help="Coefficient to convert UOM to UOS uos = uom * coeff", default=1.0)
    mes_type = fields.Selection(string="Measure Type", selection=(('fixed', 'Fixed'), ('variable', 'Variable')),
                                required=True, default='fixed')
    seller_delay = fields.Integer(string="Supplier Lead Time", compute="_calc_seller", readonly=True,
                                  help="This is the average delay in days between the purchase order confirmation and the reception of goods for this product and for the default supplier. It is used by the scheduler to order requests based on reordering delays.")
    seller_qty = fields.Float(string="Supplier Quantity", compute="_calc_seller", digits=(16, 2), readonly=True,
                              help="This is minimum quantity to purchase from Main Supplier.")
    seller_id = fields.Many2one(string="Main Supplier", compute="_calc_seller", comodel_name="res.partner",
                                readonly=True, help="Main Supplier who has highest priority in Supplier List.")
    # seller_info_id = fields.Many2one(string="Main Supplier Info", compute="_calc_seller",
    #                                  comodel_name="product.supplierinfo", readonly=True,
    #                                  help="Main Supplier who has highest priority in Supplier List - Info object.")
    # seller_ids = fields.One2many(string="Partners", comodel_name="product.supplierinfo", inverse_name="product_id")
    loc_rack = fields.Char(string="Rack", size=16)
    loc_row = fields.Char(string="Row", size=16)
    loc_case = fields.Char(string="Case", size=16)
    company_id = fields.Many2one(string="Company", comodel_name="res.company",
                                 default=lambda self: self.env.company)
    # taxes_id = fields.Many2many(string="Customer Taxes", comodel_name="account.tax", relation="product_taxes_rel",
    #                             column1="prod_id", column2="tax_id",
    #                             domain="[('parent_id', '=', False), ('type_tax_use', 'in', ['sale', 'all'])]")
    # supplier_taxes_id = fields.Many2many(string="Supplier Taxes", comodel_name="account.tax",
    #                                      relation="product_supplier_taxes_rel", column1="prod_id", column2="tax_id",
    #                                      domain="[('parent_id', '=', False), ('type_tax_use', 'in', ['purchase', 'all'])]")
    # property_account_income = fields.Many2one(string="Income Account", comodel_name="account.account",
    #                                           help="This account will be used for invoices instead of the default one to value sales for the current product",
    #                                           default=False)
    # property_account_expense = fields.Many2one(string="Expense Account", comodel_name="account.account",
    #                                            help="This account will be used for invoices instead of the default one to value expenses for the current product",
    #                                            default=False)
    # property_stock_account_input = fields.Many2one(string="Stock Input Account", comodel_name="account.account",
    #                                                help="When doing real-time inventory valuation, counterpart Journal Items for all incoming stock moves will be posted in this account. If not set on the product, the one from the product category is used.",
    #                                                default=False)
    # property_stock_account_output = fields.Many2one(string="Stock Output Account", comodel_name="account.account",
    #                                                 help="When doing real-time inventory valuation, counterpart Journal Items for all outgoing stock moves will be posted in this account. If not set on the product, the one from the product category is used.",
    #                                                 default=False)
    # property_stock_procurement = fields.Many2one(string="Procurement Location", comodel_name="stock.location",
    #                                              help="For the current product, this stock location will be used, instead of the default one, as the source location for stock moves generated by procurements",
    #                                              domain="[('usage', 'like', 'procurement')]",
    #                                              default=lambda self, cr, uid, c={}: self._get_property_stock(cr, uid,
    #                                                                                                           'location_procurement',
    #                                                                                                           context=c), )
    # property_stock_production = fields.Many2one(string="Production Location", comodel_name="stock.location",
    #                                             help="For the current product, this stock location will be used, instead of the default one, as the source location for stock moves generated by production orders",
    #                                             domain="[('usage', 'like', 'production')]",
    #                                             default=lambda self, cr, uid, c={}: self._get_property_stock(cr, uid,
    #                                                                                                          'location_production',
    #                                                                                                          context=c), )
    # property_stock_inventory = fields.Many2one(string="Inventory Location", comodel_name="stock.location",
    #                                            help="For the current product, this stock location will be used, instead of the default one, as the source location for stock moves generated when you do an inventory",
    #                                            domain="[('usage', 'like', 'inventory')]",
    #                                            default=lambda self, cr, uid, c={}: self._get_property_stock(cr, uid,
    #                                                                                                         'location_inventory',
    #                                                                                                         context=c), )
    delay_for_supplier = fields.Integer(string="Default delay for a supplier", compute="_get_delay_for_supplier",
                                        readonly=True)
    nomen_manda_0 = fields.Many2one(string="Main Type", comodel_name="product.nomenclature", required=True)
    nomen_manda_1 = fields.Many2one(string="Group", comodel_name="product.nomenclature", required=True)
    nomen_manda_2 = fields.Many2one(string="Family", comodel_name="product.nomenclature", required=True)
    nomen_manda_3 = fields.Many2one(string="Root", comodel_name="product.nomenclature", required=True)
    nomen_sub_0 = fields.Many2one(string="Sub Class 1", comodel_name="product.nomenclature")
    nomen_sub_1 = fields.Many2one(string="Sub Class 2", comodel_name="product.nomenclature")
    nomen_sub_2 = fields.Many2one(string="Sub Class 3", comodel_name="product.nomenclature")
    nomen_sub_3 = fields.Many2one(string="Sub Class 4", comodel_name="product.nomenclature")
    nomen_sub_4 = fields.Many2one(string="Sub Class 5", comodel_name="product.nomenclature")
    nomen_sub_5 = fields.Many2one(string="Sub Class 6", comodel_name="product.nomenclature")
    nomen_manda_0_s = fields.Many2one(string="Main Type", compute="_get_nomen_s", search="_search_nomen_s",
                                      comodel_name="product.nomenclature", readonly=True)
    nomen_manda_1_s = fields.Many2one(string="Group", compute="_get_nomen_s", search="_search_nomen_s",
                                      comodel_name="product.nomenclature", readonly=True)
    nomen_manda_2_s = fields.Many2one(string="Family", compute="_get_nomen_s", search="_search_nomen_s",
                                      comodel_name="product.nomenclature", readonly=True)
    nomen_manda_3_s = fields.Many2one(string="Root", compute="_get_nomen_s", search="_search_nomen_s",
                                      comodel_name="product.nomenclature", readonly=True)
    nomen_sub_0_s = fields.Many2one(string="Sub Class 1", compute="_get_nomen_s", search="_search_nomen_s",
                                    comodel_name="product.nomenclature", readonly=True)
    nomen_sub_1_s = fields.Many2one(string="Sub Class 2", compute="_get_nomen_s", search="_search_nomen_s",
                                    comodel_name="product.nomenclature", readonly=True)
    nomen_sub_2_s = fields.Many2one(string="Sub Class 3", compute="_get_nomen_s", search="_search_nomen_s",
                                    comodel_name="product.nomenclature", readonly=True)
    nomen_sub_3_s = fields.Many2one(string="Sub Class 4", compute="_get_nomen_s", search="_search_nomen_s",
                                    comodel_name="product.nomenclature", readonly=True)
    nomen_sub_4_s = fields.Many2one(string="Sub Class 5", compute="_get_nomen_s", search="_search_nomen_s",
                                    comodel_name="product.nomenclature", readonly=True)
    nomen_sub_5_s = fields.Many2one(string="Sub Class 6", compute="_get_nomen_s", search="_search_nomen_s",
                                    comodel_name="product.nomenclature", readonly=True)
    archived_nomenclature = fields.Boolean(string="Archived Nomenclature", compute="_get_archived_nomenclature",
                                           search="_search_archived_nomenclature", readonly=True)
    nomenclature_description = fields.Char(string="Nomenclature", size=1024)
    subtype = fields.Selection(string="Product SubType",
                               selection=[('single', 'Single Item'), ('kit', 'Kit/Module'), ('asset', 'Asset')],
                               required=True, help="Will change the way procurements are processed.",
                               default='single')
    # asset_type_id = fields.Many2one(string="Asset Type", comodel_name="product.asset.type")

    # Compute methods
    def _get_finance_price_currency_id(self):
        """"""
        currency = self.env.company.currency_id
        for record in self:
            record.finance_price_currency_id = currency

    # @api.depends('')
    def _get_list_price(self):
        """"""
        for record in self:
            record.list_price = 0.0

    def _calc_seller(self):
        """"""
        for record in self:
            record.seller_delay = 0
            record.seller_qty = 0.0
            record.seller_id = None
            record.seller_info_id = None

    def _get_delay_for_supplier(self):
        """"""
        for record in self:
            record.delay_for_supplier = 0

    def _get_nomen_s(self):
        """"""
        for record in self:
            record.nomen_manda_0_s = None
            record.nomen_manda_1_s = None
            record.nomen_manda_2_s = None
            record.nomen_manda_3_s = None
            record.nomen_sub_0_s = None
            record.nomen_sub_1_s = None
            record.nomen_sub_2_s = None
            record.nomen_sub_3_s = None
            record.nomen_sub_4_s = None
            record.nomen_sub_5_s = None

    def _get_archived_nomenclature(self):
        """"""
        for record in self:
            record.archived_nomenclature = False

    # Search methods
    def _search_archived_nomenclature(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _search_nomen_s(self, operator, value):
        """"""
        return [('id', operator, value)]
