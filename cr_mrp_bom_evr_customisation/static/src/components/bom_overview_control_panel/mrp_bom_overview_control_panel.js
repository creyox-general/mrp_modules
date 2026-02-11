/** @odoo-module **/

import { BomOverviewControlPanel } from "@mrp/components/bom_overview_control_panel/mrp_bom_overview_control_panel";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

patch(BomOverviewControlPanel.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.notification = useService("notification");
    },

//    async manufactureFromBoM() {
//    // Check if all components are approved
//    const bomId = this.props.data.bom_id;
//
//    try {
//        const result = await this.orm.call(
//            "mrp.bom",
//            "check_bom_components_approval",
//            [bomId]
//        );
//
//        if (!result.approved) {
//            // Show error notification with unapproved products
//            let errorMessage = _t("Cannot create Manufacturing Order. The following components are not approved for manufacturing:");
//
//            if (result.unapproved_products && result.unapproved_products.length > 0) {
//                const productList = result.unapproved_products
//                    .map(p => `• ${p.product}`)
//                    .join('\n');
//                errorMessage += '\n\n' + productList;
//                errorMessage += '\n\n' + _t("Please approve all components in their respective BOMs before creating a Manufacturing Order.");
//            }
//
//            this.notification.add(errorMessage, {
//                title: _t("Manufacturing Not Approved"),
//                type: "danger",
//                sticky: true,
//            });
//
//            return;
//        }
//
//        // If approved, call the parent implementation (which includes cr_mrp_bom_customisation logic)
//        return super.manufactureFromBoM();
//
//    } catch (error) {
//        this.notification.add(
//            _t("Error checking BOM approval status. Please try again."),
//            {
//                title: _t("Error"),
//                type: "danger",
//            }
//        );
//        console.error("Error checking BOM approval:", error);
//    }
//}
});