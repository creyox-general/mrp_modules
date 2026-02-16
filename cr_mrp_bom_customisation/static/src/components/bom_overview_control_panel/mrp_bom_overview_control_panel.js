/** @odoo-module **/

import { BomOverviewControlPanel } from "@mrp/components/bom_overview_control_panel/mrp_bom_overview_control_panel";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

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
        this.action = useService("action");
    },

    async manufactureFromBoM() {

//    if (this.props.data.is_evr) {
//        try {
//            const result = await this.orm.call(
//                "mrp.production",
//                "action_validate_and_create_mo",
//                [this.props.data.bom_id]
//            );
//
//            // 🔹 Show messages from backend
//            if (result.messages) {
//                result.messages.forEach((m) => {
//                    this.notification.add(m.msg, {
//                        title: "PO Creation",
//                        type: m.type || "info",
//                    });
//                });
//            }
//
//            return this.action.doAction(result.action);
//        } catch (e) {
//            const msg = (e && e.data && e.data.message) || e.message || "Validation failed before Manufacture.";
//            this.notification.add(msg, {
//                title: "Purchase Order Validation",
//                type: "danger",
//                sticky: true,
//            });
//            return;
//        }
//    }

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
