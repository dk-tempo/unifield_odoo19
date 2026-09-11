/** @odoo-module **/

import { X2ManyField } from "@web/views/fields/x2many/x2many_field";
import { ListRendererWithSelectionFix } from "../hooks/use_bulk_action_on_selection";

export class X2ManyFieldWithSelectors extends X2ManyField {
    static components = {
        ...X2ManyField.components,
        ListRenderer: ListRendererWithSelectionFix,
    };

    get rendererProps() {
        const props = super.rendererProps;
        props.allowSelectors = this.props.crudOptions?.enable_selection === true;
        return props;
    }
}
