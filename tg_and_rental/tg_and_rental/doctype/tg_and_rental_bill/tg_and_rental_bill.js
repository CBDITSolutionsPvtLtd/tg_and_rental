frappe.ui.form.on('TG And Rental Bill', {
    refresh: function (frm) {
        if (!frm.is_new() && frm.doc.docstatus === 1) {
            frm.add_custom_button(__('Sales Invoice'), function () {
                frappe.model.open_mapped_doc({
                    method: "tg_and_rental.tg_and_rental.doctype.tg_and_rental_bill.tg_and_rental_bill.make_sales_invoice",
                    frm: frm
                });
            }, __("Create"));
        }
    },

    copies: function (frm) {
        frm.trigger('recalculate_all');
    },

    recalculate_all: function (frm) {
        let total_copies_sum = 0;
        let total_current_copy_sum = 0;
        let total_free_copy_sum = 0;
        let total_net_copy_sum = 0;
        let total_amt_sum = 0.0;

        (frm.doc.copies || []).forEach(function (row) {
            const previous = row.previous_cc || 0;
            const current = row.current_cc || 0;
            const free = row.free_copies || 0;
            const rate = row.rate || 0;

            row.total_copies = current - previous;
            row.net_copy = row.total_copies - free;
            row.amount = row.net_copy * rate;

            total_copies_sum += row.total_copies;
            total_current_copy_sum += current;
            total_free_copy_sum += free;
            total_net_copy_sum += row.net_copy;
            total_amt_sum += row.amount;
        });

        frm.set_value('total_copies', total_copies_sum);
        frm.set_value('total_current_copy', total_current_copy_sum);
        frm.set_value('total_free_copy', total_free_copy_sum);
        frm.set_value('total_net_copy', total_net_copy_sum);
        frm.set_value('total_amt', total_amt_sum);

        // ---- DYNAMIC ACTUAL TOTAL LOGIC ----
        let monthly_fix_amt = frm.doc.monthly_fix_amt || 0;
        let comm_amt_pm = frm.doc.comm_amt_pm || 0;
        let actual_total = 0;

        if (monthly_fix_amt == 0 && comm_amt_pm > 0) {
            actual_total = (total_amt_sum < comm_amt_pm) ? comm_amt_pm : total_amt_sum;
        } else if (monthly_fix_amt > 0 && comm_amt_pm == 0) {
            actual_total = (total_amt_sum < 0) ? monthly_fix_amt : (monthly_fix_amt + total_amt_sum);
        } else {
            actual_total = total_amt_sum;
        }

        frm.set_value("actual_total", actual_total);
        frm.trigger("recalculate_taxes");
        frm.refresh_field('copies');
    },

    recalculate_taxes: function (frm) {
        let actual_total = frm.doc.actual_total || 0;
        let total_tax = 0;

        (frm.doc.taxes || []).forEach(function (row) {
            row.tax_amount = (actual_total * (row.tax_rate || 0)) / 100;
            total_tax += row.tax_amount;
        });

        frm.set_value("total_tax", total_tax);
        frm.set_value("grand_total", actual_total + total_tax);
        frm.refresh_field("taxes");

        frappe.db.get_single_value("Rent TG Setting", "overdue_charge_percent").then(percent => {
            let grand_total = frm.doc.grand_total || 0;
            let after_due_amount = grand_total + (grand_total * (percent || 0) / 100);
            frm.set_value("after_due_amount", after_due_amount);

            let rounded_total = frm.doc.enable_rounded_total
                ? Math.round(grand_total)
                : grand_total;
            frm.set_value("rounded_total", rounded_total);
        });
    },

    enable_rounded_total: function (frm) {
        frm.trigger('recalculate_taxes');
    },

    onload(frm) {
        frm.set_query('agreement_no', function () {
            return { filters: { customer: frm.doc.customer, status: 'Active' } };
        });

        // Auto-set fields when creating a new bill
        if (frm.is_new() && !frm.doc.bill_from) {
            const today = frappe.datetime.get_today();
            const first_day = frappe.datetime.month_start(today);
            const last_day = frappe.datetime.month_end(today);

            frm.set_value('bill_from', first_day);
            frm.set_value('bill_to', last_day);

            const dateObj = frappe.datetime.str_to_obj(first_day);
            const monthNames = [
                "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"
            ];
            frm.set_value('month', monthNames[dateObj.getMonth()]);
            frm.set_value('year', dateObj.getFullYear());
        }

        if (frm.doc.agreement_no && frm.doc.bill_from) {
            frm.trigger("fetch_previous_bill_values");
        }
    },

    customer(frm) {
        frm.set_query('agreement_no', function () {
            return { filters: { customer: frm.doc.customer, status: 'Active' } };
        });
    },

    agreement_no(frm) {
        if (!frm.doc.agreement_no) {
            frm.clear_table("copies");
            frm.clear_table("taxes");
            frm.refresh_field("copies");
            frm.refresh_field("taxes");
            frm.set_value('prev_total', 0);
            frm.set_value('prev_paid_amount', 0);
            frm.set_value('prev_balance', 0);
            return;
        }

        frappe.call({
            method: "tg_and_rental.tg_and_rental.doctype.rent_tg_agreement.rent_tg_agreement.get_trb_defaults",
            args: { agreement_no: frm.doc.agreement_no },
            freeze: true,
            freeze_message: __("Loading Agreement Data..."),
            callback(r) {
                if (!r.message) return;

                // Parent fields
                frm.set_value("customer", r.message.customer);
                frm.set_value("type", r.message.type);
                frm.set_value("cnt_start_dt", r.message.cnt_start_dt);
                frm.set_value("cnt_end_dt", r.message.cnt_end_dt);
                frm.set_value("comm_copies_pm", r.message.comm_copies_pm);
                frm.set_value("comm_rate_pc", r.message.comm_rate_pc);
                frm.set_value("comm_amt_pm", r.message.comm_amt_pm);
                frm.set_value("monthly_fix_amt", r.message.monthly_fix_amt);

                // Child table
                frm.clear_table("copies");
                (r.message.copies || []).forEach(row => {
                    frm.add_child("copies", {
                        item: row.item,
                        rate: row.rate,
                        free_copies: row.free_copies,
                    });
                });
                frm.refresh_field("copies");

                frm.clear_table("taxes");
                (r.message.taxes || []).forEach(row => {
                    frm.add_child("taxes", {
                        type: row.type,
                        tax_rate: row.tax_rate,
                        tax_amount: row.tax_amount
                    });
                });
                frm.refresh_field("taxes");

                frm.trigger("fetch_previous_cc_batch");
                if (frm.doc.bill_from) {
                    frm.trigger("fetch_previous_bill_values");
                }
                frm.trigger("recalculate_all");
            }
        });
    },

    // 🧊 Freeze-enabled async fetch for previous_cc
    fetch_previous_cc_batch(frm) {
        if (frm.doc.manual_previous_cc) {
        // Skip auto-fetch if manual mode is on
            frappe.show_alert({
                message: __("Manual Previous CC mode is ON — system won't auto-update Previous CC."),
                indicator: 'blue'
            });
            frm.trigger("recalculate_all");
            return;
        }

        if (!frm.doc.agreement_no || !frm.doc.bill_from || !frm.doc.copies || frm.doc.copies.length === 0) {
            frm.trigger("recalculate_all");
            return;
        }

        let items = frm.doc.copies.map(row => row.item).filter(item => item);
        if (items.length === 0) {
            frm.trigger("recalculate_all");
            return;
        }

        frappe.call({
            method: "tg_and_rental.tg_and_rental.doctype.tg_and_rental_bill.tg_and_rental_bill.get_previous_cc_batch",
            args: {
                agreement_no: frm.doc.agreement_no,
                bill_from: frm.doc.bill_from,
                items_json: JSON.stringify(items)
            },
            freeze: true,
            freeze_message: __("Fetching Previous CC values..."),
            async: true,
            callback(r) {
                if (r.message) {
                    frm.doc.copies.forEach(row => {
                        if (row.item && r.message[row.item] !== undefined) {
                            frappe.model.set_value(row.doctype, row.name, 'previous_cc', r.message[row.item]);
                        }
                    });

                    frm.refresh_field('copies');
                    frm.trigger('recalculate_all');
                }
            }
        });
    },

    fetch_previous_bill_values(frm) {
        if (!frm.doc.agreement_no || !frm.doc.bill_from) {
            frm.set_value('prev_total', 0);
            frm.set_value('prev_paid_amount', 0);
            frm.set_value('prev_balance', 0);
            return;
        }

        frappe.call({
            method: "tg_and_rental.tg_and_rental.doctype.tg_and_rental_bill.tg_and_rental_bill.get_previous_bill_values",
            args: {
                agreement_no: frm.doc.agreement_no,
                bill_from: frm.doc.bill_from,
                name: frm.doc.name || null
            },
            freeze: true,
            freeze_message: __("Updating previous bill data..."),
            async: true,
            callback(r) {
                if (r.message) {
                    frm.set_value('prev_total', r.message.prev_total || 0);
                    frm.set_value('prev_paid_amount', r.message.prev_paid_amount || 0);
                    frm.set_value('prev_balance', r.message.prev_balance || 0);
                } else {
                    frm.set_value('prev_total', 0);
                    frm.set_value('prev_paid_amount', 0);
                    frm.set_value('prev_balance', 0);
                }
                frm.refresh_field(['prev_total', 'prev_paid_amount', 'prev_balance']);
            }
        });
    },

    bill_from(frm) {
        if (!frm.doc.bill_from) return;

        const bill_from = frappe.datetime.str_to_obj(frm.doc.bill_from);
        const next_month_same_day = frappe.datetime.add_months(bill_from, 1);
        const bill_to = frappe.datetime.add_days(next_month_same_day, -1);
        frm.set_value('bill_to', frappe.datetime.obj_to_str(bill_to));

        const monthNames = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ];
        frm.set_value('month', monthNames[bill_from.getMonth()]);
        frm.set_value('year', bill_from.getFullYear());

        // Fetch previous_cc + previous bill values immediately
        if (frm.doc.agreement_no) {
            frm.trigger("fetch_previous_cc_batch");
            frm.trigger("fetch_previous_bill_values");
        }
    }
});

frappe.ui.form.on('Rented Items Table', {
    current_cc(frm) { frm.trigger('recalculate_all'); },
    previous_cc(frm) { frm.trigger('recalculate_all'); },
    free_copies(frm) { frm.trigger('recalculate_all'); },
    rate(frm) { frm.trigger('recalculate_all'); }
});

frappe.ui.form.on('Custom Tax Charges Template', {
    tax_rate(frm) { frm.trigger('recalculate_taxes'); }
});
