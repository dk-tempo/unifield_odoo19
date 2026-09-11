/** @odoo-module **/

import { Component } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";

export class FilterToolbar extends Component {
    static template = "filter_selector.FilterToolbar";
    static components = { Dropdown, DropdownItem };
    static props = {
        options: Array,
        selected: Number,
        onSelect: Function,
        searchFields: Array,
        searchValues: Object,
        onSearch: Function,
    };

    get selectedLabel() {
        return this.props.options[this.props.selected]?.[0] ?? "";
    }

    placeholderFor(field) {
        return `Contient... (${field})`;
    }

    onInput(field, ev) {
        this.props.onSearch(field, ev.target.value);
    }
}
