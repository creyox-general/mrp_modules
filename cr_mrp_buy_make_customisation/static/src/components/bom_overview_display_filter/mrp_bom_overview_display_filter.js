/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { BomOverviewDisplayFilter } from "@mrp/components/bom_overview_display_filter/mrp_bom_overview_display_filter";

patch(BomOverviewDisplayFilter.prototype, {
    setup() {
        super.setup();
        this.displayOptions.buyMakeSelection = _t('Buy / Make');
    },
});

patch(BomOverviewDisplayFilter, {
    props: {
        ...BomOverviewDisplayFilter.props,
        showOptions: {
            ...BomOverviewDisplayFilter.props.showOptions,
            buyMakeSelection: Boolean,
        },
    },
});