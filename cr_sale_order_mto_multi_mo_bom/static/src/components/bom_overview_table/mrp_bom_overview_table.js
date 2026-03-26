/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { BomOverviewTable } from "@mrp/components/bom_overview_table/mrp_bom_overview_table";

patch(BomOverviewTable.prototype, {
    /**
     * Open related records. 
     * If 1 record: open form view directly.
     * If multi records: open list view with domain.
     */
    async openRecords(resModel, resIds, title) {
        if (!resIds || resIds.length === 0) {
            return;
        }

        const action = {
            type: "ir.actions.act_window",
            res_model: resModel,
            name: title,
            target: "current",
        };

        if (resIds.length === 1) {
            action.res_id = resIds[0];
            action.views = [[false, "form"]];
        } else {
            action.domain = [["id", "in", resIds]];
            action.views = [[false, "list"], [false, "form"]];
        }

        return this.actionService.doAction(action);
    },
});
