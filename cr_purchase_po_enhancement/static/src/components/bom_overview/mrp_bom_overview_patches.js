/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { BomOverviewComponent } from "@mrp/components/bom_overview/mrp_bom_overview";
import { BomOverviewDisplayFilter } from "@mrp/components/bom_overview_display_filter/mrp_bom_overview_display_filter";
import { BomOverviewTable } from "@mrp/components/bom_overview_table/mrp_bom_overview_table";
import { BomOverviewLine } from "@mrp/components/bom_overview_line/mrp_bom_overview_line";

// ── Default Special PO option to false ─────────────────────────────────────
patch(BomOverviewComponent.prototype, {
    setup() {
        super.setup();
        this.state.showOptions.specialPo = false;
    },
});

patch(BomOverviewLine, {
    props: {
        ...BomOverviewLine.props,
        showOptions: {
            ...BomOverviewLine.props.showOptions,
            specialPo: Boolean,
        },
    },
});

// ── Add Special PO to display filters ──────────────────────────────────────
patch(BomOverviewDisplayFilter.prototype, {
    setup() {
        super.setup();
        this.displayOptions.specialPo = _t('Create Special PO');
    },
});

patch(BomOverviewDisplayFilter, {
    props: {
        ...BomOverviewDisplayFilter.props,
        showOptions: {
            ...BomOverviewDisplayFilter.props.showOptions,
            specialPo: Boolean,
        },
    },
});

// ── Add Special PO to Table props ──────────────────────────────────────────
patch(BomOverviewTable.prototype, {
    get showSpecialPo() {
        return this.props.showOptions.specialPo;
    },
});

patch(BomOverviewTable, {
    props: {
        ...BomOverviewTable.props,
        showOptions: {
            ...BomOverviewTable.props.showOptions,
            specialPo: Boolean,
        },
    },
});
