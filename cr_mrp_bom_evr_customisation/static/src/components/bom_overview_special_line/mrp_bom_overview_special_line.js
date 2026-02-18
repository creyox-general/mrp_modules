/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { BomOverviewSpecialLine } from "@mrp/components/bom_overview_special_line/mrp_bom_overview_special_line";

patch(BomOverviewSpecialLine.prototype, {
    get showCfeQuantity() {
        return this.props.showOptions.cfeQuantity;
    },
    get showMoInternalRef() {
        return this.props.showOptions.moInternalRef;
    },
    get showLli() {
        return this.props.showOptions.lli;
    },
    get showApproval1() {
        return this.props.showOptions.approval1;
    },
    get showApproval2() {
        return this.props.showOptions.approval2;
    },
    get showDefaultCode() {
        return this.props.showOptions.defaultCode;
    },
    get showOldEverestPn() {
        return this.props.showOptions.oldEverestPn;
    },
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
            cfeQuantity: Boolean,
            moInternalRef: Boolean,
            lli: Boolean,
            approval1: Boolean,
            approval2: Boolean,
            defaultCode: Boolean,
            oldEverestPn: Boolean,
            approveToManufacture: Boolean,
            purchaseGroup: Boolean,
            freeToUse: Boolean,
            displayCost: Boolean,
            customerRef: Boolean,
            poLineId: Boolean,
        },
    },
});