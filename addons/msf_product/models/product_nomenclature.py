from odoo import api, fields, models, _

from odoo.exceptions import ValidationError

# Maximum depth of level
_LEVELS = 4
# (Max?) number of sub levels (optional levels)
_SUB_LEVELS = 6

class ProductNomenclature(models.Model):
    _name = "product.nomenclature"
    _description = "Product Nomenclature"
    _parent_name = "parent_id"
    _parent_store = True
    _rec_name = "complete_name"

    active = fields.Boolean(string="Active",
                            help="If the active field is set to False, it allows to hide the nomenclature without removing it.",
                            default=True)
    name = fields.Char(string="Name", translate=1, size=128, required=True)
    parent_path = fields.Char(index=True)
    complete_name = fields.Char(string="Full name", compute="_name_get_fnc", search="_search_complete_name",
                                readonly=True)
    parent_id = fields.Many2one(string="Parent Nomenclature", comodel_name="product.nomenclature", index=True)
    child_id = fields.One2many(string="Child Nomenclatures", comodel_name="product.nomenclature",
                               inverse_name="parent_id")
    sequence = fields.Integer(string="Sequence", index=True,
                              help="Gives the sequence order when displaying a list of product nomenclatures.",
                              default=0)
    level = fields.Integer(string="Level", compute="_compute_level", store=True, recursive=True, index=True)
    type = fields.Selection(string="Nomenclature Type", index=True,
                            selection=[('mandatory', 'Mandatory'), ('optional', 'Optional')],
                            default='mandatory')
    sub_level = fields.Selection(string="Sub-Level",
                                 selection=[('0', '1'), ('1', '2'), ('2', '3'), ('3', '4'), ('4', '5'), ('5', '6')],
                                 default='0')
    number_of_products = fields.Integer(string="Number of Products", compute="_getNumberOfProducts", readonly=True)
    category_id = fields.Many2one(string="Category", compute="_get_category_id", search="_src_category_id",
                                  comodel_name="product.category", readonly=True,
                                  help="If empty, please contact accounting member to create a new product category associated to this family.")
    category_ids = fields.One2many(string="Categories", comodel_name="product.category", inverse_name="family_id")
    nomen_manda_0_s = fields.Many2one(string="Main Type", compute="_get_nomen_s", search="_search_nomen_s",
                                      comodel_name="product.nomenclature", readonly=True)
    nomen_manda_1_s = fields.Many2one(string="Group", compute="_get_nomen_s", search="_search_nomen_s",
                                      comodel_name="product.nomenclature", readonly=True)
    nomen_manda_2_s = fields.Many2one(string="Family", compute="_get_nomen_s", search="_search_nomen_s",
                                      comodel_name="product.nomenclature", readonly=True)
    nomen_manda_3_s = fields.Many2one(string="Root", compute="_get_nomen_s", search="_search_nomen_s",
                                      comodel_name="product.nomenclature", readonly=True)
    msfid = fields.Char(string="MSFID", size=128, index=True)
    status = fields.Selection(string="Status", selection=[('valid', 'Valid'), ('archived', 'Archived')], readonly=True,
                              default="valid")

    # Compute methods
    @api.depends('parent_id.level')
    def _compute_level(self):
        for record in self:
            current_level = 0 if not record.parent_id else record.parent_id.level + 1
            if current_level > _LEVELS:
                raise ValidationError(_('The selected nomenclature should not be proposed.'))
            if current_level == _LEVELS and record.type == "mandatory":
                raise ValidationError(_("You selected a nomenclature of the last mandatory level as parent, "
                                        "the new nomenclature's type must be 'optional'."))
            record.level = current_level

    def _name_get_fnc(self):
        """"""
        for nomen in self:
            complete_name = nomen.name
            nomen.complete_name = complete_name

    def _getNumberOfProducts(self):
        """Returns the number of products for the nomenclature"""
        for nomen in self:
            level_name = ''
            if nomen.type == 'mandatory':
                level_name = 'nomen_manda_%s' % nomen.level
            if nomen.type == 'optional':
                level_name = 'nomen_sub_%s' % nomen.sub_level
            products_count = self.env['product.product'].search_count([(level_name, '=', nomen.id)])
            nomen.number_of_products = products_count

    def _get_category_id(self):
        """Returns the first category of the nomenclature"""
        for nom in self:
            if nom.category_ids:
                nom.category_id = nom.category_ids[0].id
            else:
                nom.category_id = None

    def _get_nomen_s(self):
        """"""
        for nomen in self:
            current_nomen = nomen
            for level in range(3, -1, -1):
                if level == 3:
                    nomen.nomen_manda_3_s = None if nomen.level < level else current_nomen
                if level == 2:
                    nomen.nomen_manda_2_s = None if nomen.level < level else current_nomen
                if level == 1:
                    nomen.nomen_manda_1_s = None if nomen.level < level else current_nomen
                if level == 0:
                    nomen.nomen_manda_0_s = None if nomen.level < level else current_nomen

                if current_nomen and current_nomen.level == level:
                    current_nomen = None if not current_nomen.parent_id else current_nomen.parent_id

    # Search methods
    def _search_complete_name(self, operator, value):
        return [('parent_path', 'ilike', value)]

    def _search_nomen_s(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _src_category_id(self, operator, value):
        """"""
        return [('id', operator, value)]

    def _search_custom_name(self, operator, value):
        """"""
        return [('id', operator, value)]

