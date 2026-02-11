/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { BomOverviewSpecialLine } from "@mrp/components/bom_overview_special_line/mrp_bom_overview_special_line";

patch(BomOverviewSpecialLine.prototype, {
    get showApproveToManufacture() {
        return this.props.showOptions.approveToManufacture;
    },
    get showPurchaseGroup() {
        return this.props.showOptions.purchaseGroup;
    },
    get showFreeToUse() {
        return this.props.showOptions.freeToUse;
    },
    get showDisplayCost() {
        return this.props.showOptions.displayCost;
    },
    get showCustomerRef() {
        return this.props.showOptions.customerRef;
    },
    get showPoLineId() {
        return this.props.showOptions.poLineId;
    }
});

patch(BomOverviewSpecialLine, {
    props: {
        ...BomOverviewSpecialLine.props,
        showOptions: {
            ...BomOverviewSpecialLine.props.showOptions,
            approveToManufacture: Boolean,
            purchaseGroup: Boolean,
            freeToUse: Boolean,
            displayCost: Boolean,
            customerRef: Boolean,
            poLineId: Boolean,
        },
    },
});