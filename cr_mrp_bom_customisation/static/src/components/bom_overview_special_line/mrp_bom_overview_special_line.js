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
        },
    },
});