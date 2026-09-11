/** @odoo-module **/

import { useEnv, useSubEnv } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ListRenderer } from "@web/views/list/list_renderer";

export class ListRendererWithSelectionFix extends ListRenderer {
    toggleSelection() {
        if (!this.canSelectRecord) {
            return;
        }
        const records = this.props.list.records;
        const selection = records.filter((r) => r.selected);
        const selectAll = selection.length !== records.length;
        for (const record of records) {
            record.toggleSelection(selectAll);
        }
    }
}

export function useBulkActionOnSelection(getList) {
    const env = useEnv();
    const dialog = useService("dialog");
    const parentOnClickViewButton = env.onClickViewButton;

    useSubEnv({
        onClickViewButton: (params) => {
            const resParams = params.getResParams();
            const selection = getList().records.filter((r) => r.selected);
            const clickedIsSelected = selection.some((r) => r.resId === resParams.resId);

            if (selection.length > 1 && clickedIsSelected) {
                const actionName = params.clickParams.name || "cette action";
                return new Promise((resolve) => {
                    dialog.add(ConfirmationDialog, {
                        title: "Confirm",
                        body: `You are about to apply “${actionName}” to ${selection.length} rows. Are you sure?`,
                        confirm: async () => {
                            const resIds = selection.map((r) => r.resId);
                            const result = await parentOnClickViewButton({
                                ...params,
                                getResParams: () => ({ ...resParams, resId: false, resIds }),
                            });
                            resolve(result);
                        },
                        cancel: () => resolve(false),
                    });
                });
            }
            return parentOnClickViewButton(params);
        },
    });
}