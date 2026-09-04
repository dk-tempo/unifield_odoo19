from odoo import api, fields, models


class ProductJustificationCode(models.Model):
    _name = 'product.justification.code'
    _description = 'product.justification.code'
    _order = 'code'
    _rec_name = 'code'

    code = fields.Char(string="Justification Code", translate=True, size=32, required=True)
    description = fields.Char(string="Justification Description", translate=True, size=256, required=True)
