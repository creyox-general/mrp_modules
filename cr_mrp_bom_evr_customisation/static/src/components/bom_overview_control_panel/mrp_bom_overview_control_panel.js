/** @odoo-module **/

import { BomOverviewControlPanel } from "@mrp/components/bom_overview_control_panel/mrp_bom_overview_control_panel";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

patch(BomOverviewControlPanel, {
    props: {
        ...BomOverviewControlPanel.props,
        isEvr: { type: Boolean, optional: true },
    },
});

patch(BomOverviewControlPanel.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.notification = useService("notification");
    },

    async manufactureFromBoM() {
        const action = {
            res_model: "mrp.production",
            name: "Manufacture Orders",
            type: "ir.actions.act_window",
            views: [[false, "form"]],
            target: "current",
            context: { default_bom_id: this.props.data.bom_id },
        };
        return this.action.doAction(action);
    },

});