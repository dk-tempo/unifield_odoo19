from odoo import api, fields, models


class ResPartnerAddress(models.Model):
    _name = "res.partner.address"
    _description = "Partner Address"

    partner_id = fields.Many2one(string="Partner Name", comodel_name="res.partner",
                                 help="Keep empty for a private address, not related to partner.")
    type = fields.Selection(string="Address Type",
                            selection=[('default', 'Default'), ('invoice', 'Invoice'), ('delivery', 'Delivery'),
                                       ('contact', 'Contact'), ('other', 'Other')],
                            help="Used to select automatically the right address according to the context in sales and purchases documents.")
    function = fields.Char(string="Function", size=64)
    title = fields.Many2one(string="Title", comodel_name="res.partner.title")
    name = fields.Char(string="Contact Name", size=64)
    street = fields.Char(string="Street", size=128)
    street2 = fields.Char(string="Street2", size=128)
    zip = fields.Char(string="Zip", size=24)
    city = fields.Char(string="City", size=128)
    state_id = fields.Many2one(string="Fed. State", comodel_name="res.country.state",
                               domain="[('country_id','=',country_id)]")
    country_id = fields.Many2one(string="Country", comodel_name="res.country")
    email = fields.Char(string="E-Mail", size=240)
    phone = fields.Char(string="Phone", size=64)
    fax = fields.Char(string="Fax", size=64)
    mobile = fields.Char(string="Mobile", size=64)
    birthdate = fields.Char(string="Birthdate", size=64)
    is_customer_add = fields.Boolean(string="Customer", related="partner_id.customer", readonly=True)
    is_supplier_add = fields.Boolean(string="Supplier", related="partner_id.supplier", readonly=True)
    active = fields.Boolean(string="Active", help="Uncheck the active field to hide the contact.",
                            default=True)
    company_id = fields.Many2one(string="Company", comodel_name="res.company",
                                 default=lambda self: self.env.company)
    office_name = fields.Char(string="Office name", size=128)
    dest_address = fields.Boolean(string="Dest. Address", compute="_get_dummy", search="_src_address", readonly=True)
    inv_address = fields.Boolean(string="Invoice Address", compute="_get_dummy", search="_src_address", readonly=True)

    # Compute methods
    def _get_dummy(self):
        """"""
        for record in self:
            record.dest_address = False
            record.inv_address = False

    # Search methods
    def _src_address(self, operator, value):
        """"""
        return [('id', operator, value)]
