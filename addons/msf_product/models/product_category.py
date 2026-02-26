from odoo import api, fields, models


class ProductCategory(models.Model):
    _name = "product.category"
    _description = "Product Category"
    _parent_name = "parent_id"

    name = fields.Char(string="Name", translate=True, size=64, required=True)
    complete_name = fields.Char(string="Full Name", compute="_name_get_fnc", readonly=True)
    parent_id = fields.Many2one(string="Parent Category", comodel_name="product.category")
    child_id = fields.One2many(string="Child Categories", comodel_name="product.category", inverse_name="parent_id")
    sequence = fields.Integer(string="Sequence",
                              help="Gives the sequence order when displaying a list of product categories.")
    type = fields.Selection(string="Category Type", selection=[('view', 'View'), ('normal', 'Normal')],
                            default='normal', )
    # property_account_income_categ = fields.Many2one(string="Income Account", comodel_name="account.account",
    #                                                 help="This account will be used for invoices to value sales for the current product category")
    # property_account_expense_categ = fields.Many2one(string="Expense Account", comodel_name="account.account",
    #                                                  help="This account will be used for invoices to value expenses for the current product category")
    # asset_bs_account_id = fields.Many2one(string="Asset Balance Sheet Account", comodel_name="account.account",
    #                                       domain="[('type', '=', 'other'), ('user_type_code', '=', 'asset')]")
    # asset_bs_depreciation_account_id = fields.Many2one(string="Asset B/S Depreciation Account",
    #                                                    comodel_name="account.account",
    #                                                    domain="[('type', '=', 'other'), ('user_type_code', '=', 'asset')]")
    # asset_pl_account_id = fields.Many2one(string="Asset P&L Depreciation Account", comodel_name="account.account",
    #                                       domain="[('user_type_code', 'in', ['expense', 'income'])]")
    # property_stock_journal = fields.Many2one(string="Stock journal", comodel_name="account.journal",
    #                                          help="When doing real-time inventory valuation, this is the Accounting Journal in which entries will be automatically posted when stock moves are processed.")
    # property_stock_account_input_categ = fields.Many2one(string="Stock Input Account", comodel_name="account.account",
    #                                                      help="When doing real-time inventory valuation, counterpart Journal Items for all incoming stock moves will be posted in this account. This is the default value for all products in this category, it can also directly be set on each product.")
    # property_stock_account_output_categ = fields.Many2one(string="Stock Output Account", comodel_name="account.account",
    #                                                       help="When doing real-time inventory valuation, counterpart Journal Items for all outgoing stock moves will be posted in this account. This is the default value for all products in this category, it can also directly be set on each product.")
    # property_stock_variation = fields.Many2one(string="Stock Variation Account", comodel_name="account.account",
    #                                            help="When real-time inventory valuation is enabled on a product, this account will hold the current value of the products.")
    # donation_expense_account = fields.Many2one(string="Donation Account", comodel_name="account.account")
    active = fields.Boolean(string="Active",
                            help="If the active field is set to False, it allows to hide the nomenclature without removing it.",
                            default=True)
    family_id = fields.Many2one(string="Family", comodel_name="product.nomenclature",
                                domain="[('level', '=', '2'), ('type', '=', 'mandatory'), ('category_id', '=', False)]")
    msfid = fields.Char(string="MSFID", size=128)

    # Compute methods
    def _name_get_fnc(self):
        """"""
        for record in self:
            complete_name = record.name
            if record.parent_id:
                complete_name = f"{record.parent_id.name} / {complete_name}"
            record.complete_name = complete_name
