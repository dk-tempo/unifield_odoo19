from odoo import api, fields, models


class ProductSectionCode(models.Model):
    _name = 'product.section.code'
    _description = 'Product Section Code'
    _order = 'id'
    _rec_name = 'code'

    code = fields.Char(string="Code", size=4)
    section = fields.Char(string="Section", size=32)
    description = fields.Char(string="Description", size=128)
