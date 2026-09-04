from odoo import api, fields, models


class ProductListLine(models.Model):
    _name = 'product.list.line'
    _description = 'Line of product list'
    _order = 'ref'

    name = fields.Many2one(string="Product Description", comodel_name="product.product", ondelete="restrict",
                           required=True)
    list_id = fields.Many2one(string="List", comodel_name="product.list", ondelete="cascade")
    ref = fields.Char(string="Product Code", related="name.default_code", store=True, size=64, readonly=True)
    desc = fields.Char(string="Product Description", related="name.name", store=True, size=128, readonly=True)
    comment = fields.Char(string="Comment", size=256)
    mml_status = fields.Selection(string="MML", compute="_get_std_mml_status",
                                  selection=[('T', 'Yes'), ('F', 'No'), ('na', '')], readonly=True, default="na")
    msl_status = fields.Selection(string="MSL", compute="_get_std_mml_status",
                                  selection=[('T', 'Yes'), ('F', 'No'), ('na', '')], readonly=True, default="na")

    # Compute methods
    def _get_std_mml_status(self):
        """"""
        for record in self:
            record.mml_status = ""
            record.msl_status = ""
