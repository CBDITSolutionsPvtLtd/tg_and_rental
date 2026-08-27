frappe.ui.form.on("Rent TG Agreement", {
    refresh: function(frm) {
        frm.trigger("calculate_end_date");
        frm.trigger("calculate_committed_amount");
        frm.trigger("toggle_commitment_mode");

        frm.trigger("set_machine_filter");
        frm.trigger("set_customer_dependent_filters");

        // show button only when Active + submitted
        if (frm.doc.docstatus === 1 && frm.doc.status === "Active") {
            frm.add_custom_button("Create TG And Rental Bill", function() {
                frappe.call({
                    method: "tg_and_rental.tg_and_rental.doctype.rent_tg_agreement.rent_tg_agreement.make_trb",
                    args: { source_name: frm.doc.name },
                    callback(r) {
                        if (r.message) {
                            frappe.model.sync(r.message);
                            frappe.set_route("Form", r.message.doctype, r.message.name);
                        }
                    }
                });
            }, __("Create"));
        }
    },

    onload: function(frm) {
        frm.trigger("set_machine_filter");
        frm.trigger("set_customer_dependent_filters");
    },

    machine_make: function(frm) {
        frm.trigger("set_machine_filter");
    },

    set_machine_filter: function(frm) {
        frm.set_query("machine", function() {
            let filters = { rental_product: 1 };
            if (frm.doc.machine_make) {
                filters["brand"] = ["=", frm.doc.machine_make];
            }
            return { filters: filters };
        });
    },

    machine: function(frm) {
        if (frm.doc.machine) {
            frappe.db.get_value("Item", frm.doc.machine, ["model_no"], function(value) {
                if (value && value.model_no) {
                    frm.set_value("model_no", value.model_no);
                } else {
                    frm.set_value("model_no", "");
                }
            });
        } else {
            frm.set_value("model_no", "");
        }
    },

    // ---------------------------------------------------------------
    // Customer -> Address / Contact filtering
    // Uses the built-in server-side address_query / contact_query
    // methods instead of a raw {link_name: customer} filter, because
    // in v16 the framework enforces field-level permission checks on
    // filter fields (link_name / link_doctype) which raises:
    //   "You do not have permission to access field: Address.link_name"
    // address_query / contact_query run their own SQL and are not
    // affected by that restriction.
    // ---------------------------------------------------------------
    set_customer_dependent_filters: function(frm) {
        frm.set_query("customer_address", () => ({
            query: "frappe.contacts.doctype.address.address.address_query",
            filters: {
                link_doctype: "Customer",
                link_name: frm.doc.customer
            }
        }));

        frm.set_query("contact", () => ({
            query: "frappe.contacts.doctype.contact.contact.contact_query",
            filters: {
                link_doctype: "Customer",
                link_name: frm.doc.customer
            }
        }));
    },

    customer: function(frm) {
        // Refresh the link-field queries for the newly selected customer
        frm.trigger("set_customer_dependent_filters");

        // Clear dependent fields when customer changes
        frm.set_value("customer_address", "");
        frm.set_value("contact", "");
        frm.set_value("gst_no", "");
        frm.set_value("address_line1", "");
        frm.set_value("address_line2", "");
        frm.set_value("city", "");
        frm.set_value("state", "");
        frm.set_value("pincode", "");
        frm.set_value("contact_person", "");
        frm.set_value("contact_number", "");
    },

    customer_address: function(frm) {
        if (!frm.doc.customer_address) return;

        frappe.db.get_doc("Address", frm.doc.customer_address)
            .then(address => {
                frm.set_value("address_line1", address.address_line1 || "");
                frm.set_value("address_line2", address.address_line2 || "");
                frm.set_value("city", address.city || "");
                frm.set_value("state", address.state || "");
                frm.set_value("pincode", address.pincode || "");

                // Try to get GST from Address first
                if (address.gstin) {
                    frm.set_value("gst_no", address.gstin);
                } else if (frm.doc.customer) {
                    // Else get GST from Customer
                    frappe.db.get_value("Customer", frm.doc.customer, "gstin", r => {
                        frm.set_value("gst_no", r.gstin || "");
                    });
                }
            });
    },

    contact: function(frm) {
        if (!frm.doc.contact) return;

        frappe.db.get_doc("Contact", frm.doc.contact)
            .then(contact => {
                let full_name = (contact.first_name || "") +
                                (contact.last_name ? " " + contact.last_name : "");
                frm.set_value("contact_person", full_name.trim());

                let phone_number = contact.mobile_no || contact.phone || "";
                frm.set_value("contact_number", phone_number);
            });
    },

    start_date(frm) { frm.trigger("calculate_end_date"); },
    time_duration(frm) { frm.trigger("calculate_end_date"); },
    time_unit(frm) { frm.trigger("calculate_end_date"); },

    comm_copies_pm(frm) { frm.trigger("calculate_committed_amount"); },
    comm_rate_pc(frm) { frm.trigger("calculate_committed_amount"); },

    calculate_end_date(frm) {
        const start = frm.doc.start_date;
        const duration = frm.doc.time_duration;
        const unit = frm.doc.time_unit;

        if (!start || !duration || !unit) {
            frm.set_value("end_date", null);
            return;
        }

        let end_exclusive = null;

        if (unit === "Day") {
            end_exclusive = frappe.datetime.add_days(start, duration);
        } else if (unit === "Week") {
            end_exclusive = frappe.datetime.add_days(start, duration * 7);
        } else if (unit === "Month") {
            end_exclusive = frappe.datetime.add_months(start, duration);
        } else if (unit === "Year") {
            end_exclusive = frappe.datetime.add_months(start, duration * 12);
        }

        if (end_exclusive) {
            const end_inclusive = frappe.datetime.add_days(end_exclusive, -1);
            frm.set_value("end_date", end_inclusive);
        } else {
            frm.set_value("end_date", null);
        }
    },

    calculate_committed_amount(frm) {
        if (frm.doc.copy_commitment) {
            const ccpm = frm.doc.comm_copies_pm || 0;
            const crpc = frm.doc.comm_rate_pc || 0;
            frm.set_value("comm_amt_pm", ccpm > 0 && crpc > 0 ? ccpm * crpc : 0);
        }
    },

    // Commitment checkboxes
    copy_commitment(frm) {
        if (frm.doc.copy_commitment) {
            frm.set_value("amount_commitment", 0); // uncheck other
        }
        frm.trigger("toggle_commitment_mode");
    },

    amount_commitment(frm) {
        if (frm.doc.amount_commitment) {
            frm.set_value("copy_commitment", 0); // uncheck other
        }
        frm.trigger("toggle_commitment_mode");
    },

    toggle_commitment_mode(frm) {
        if (frm.doc.copy_commitment) {
            frm.set_df_property("comm_copies_pm", "read_only", 0);
            frm.set_df_property("comm_rate_pc", "read_only", 0);
            frm.set_df_property("comm_amt_pm", "read_only", 1);
            frm.trigger("calculate_committed_amount");
        } else if (frm.doc.amount_commitment) {
            frm.set_df_property("comm_copies_pm", "read_only", 1);
            frm.set_df_property("comm_rate_pc", "read_only", 1);
            frm.set_df_property("comm_amt_pm", "read_only", 0);
            frm.set_value("comm_copies_pm", 0);
            frm.set_value("comm_rate_pc", 0);
        } else {
            // neither selected → everything editable
            frm.set_df_property("comm_copies_pm", "read_only", 1);
            frm.set_df_property("comm_rate_pc", "read_only", 1);
            frm.set_df_property("comm_amt_pm", "read_only", 1);
        }
    }
});




// frappe.ui.form.on("Rent TG Agreement", {
//     refresh: function(frm) {
//         frm.trigger("calculate_end_date");
//         frm.trigger("calculate_committed_amount");
//         frm.trigger("toggle_commitment_mode");

//         frm.trigger("set_machine_filter");

//         // show button only when Active + submitted
//         if (frm.doc.docstatus === 1 && frm.doc.status === "Active") {
//             frm.add_custom_button("Create TG And Rental Bill", function() {
//                 frappe.call({
//                     method: "tg_and_rental.tg_and_rental.doctype.rent_tg_agreement.rent_tg_agreement.make_trb",
//                     args: { source_name: frm.doc.name },
//                     callback(r) {
//                         if (r.message) {
//                             frappe.model.sync(r.message);
//                             frappe.set_route("Form", r.message.doctype, r.message.name);
//                         }
//                     }
//                 });
//             }, __("Create"));
//         }
//     },

//     onload: function(frm) {
//         frm.trigger("set_machine_filter");
//     },
//     machine_make: function(frm) {
//         frm.trigger("set_machine_filter");
//     },

//     set_machine_filter: function(frm) {
//         frm.set_query("machine", function() {
//             let filters = { rental_product: 1 };
//             if (frm.doc.machine_make) {
//                 filters["brand"] = ["=", frm.doc.machine_make];
//             }
//             return { filters: filters };
//         });
//     },

//     machine: function(frm) {
//         if (frm.doc.machine) {
//             frappe.db.get_value("Item", frm.doc.machine, ["model_no"], function(value) {
//                 if (value && value.model_no) {
//                     frm.set_value("model_no", value.model_no);
//                 } else {
//                     frm.set_value("model_no", "");
//                 }
//             });
//         } else {
//             frm.set_value("model_no", "");
//         }
//     },


//     start_date(frm) { frm.trigger("calculate_end_date"); },
//     time_duration(frm) { frm.trigger("calculate_end_date"); },
//     time_unit(frm) { frm.trigger("calculate_end_date"); },

//     comm_copies_pm(frm) { frm.trigger("calculate_committed_amount"); },
//     comm_rate_pc(frm) { frm.trigger("calculate_committed_amount"); },

//     calculate_end_date(frm) {
//         const start = frm.doc.start_date;
//         const duration = frm.doc.time_duration;
//         const unit = frm.doc.time_unit;

//         if (!start || !duration || !unit) {
//             frm.set_value("end_date", null);
//             return;
//         }

//         let end_exclusive = null;

//         if (unit === "Day") {
//             end_exclusive = frappe.datetime.add_days(start, duration);
//         } else if (unit === "Week") {
//             end_exclusive = frappe.datetime.add_days(start, duration * 7);
//         } else if (unit === "Month") {
//             end_exclusive = frappe.datetime.add_months(start, duration);
//         } else if (unit === "Year") {
//             end_exclusive = frappe.datetime.add_months(start, duration * 12);
//         }

//         if (end_exclusive) {
//             const end_inclusive = frappe.datetime.add_days(end_exclusive, -1);
//             frm.set_value("end_date", end_inclusive);
//         } else {
//             frm.set_value("end_date", null);
//         }
//     },

//     calculate_committed_amount(frm) {
//         if (frm.doc.copy_commitment) {
//             const ccpm = frm.doc.comm_copies_pm || 0;
//             const crpc = frm.doc.comm_rate_pc || 0;
//             frm.set_value("comm_amt_pm", ccpm > 0 && crpc > 0 ? ccpm * crpc : 0);
//         }
//     },

//     // Commitment checkboxes
//     copy_commitment(frm) {
//         if (frm.doc.copy_commitment) {
//             frm.set_value("amount_commitment", 0); // uncheck other
//         }
//         frm.trigger("toggle_commitment_mode");
//     },

//     amount_commitment(frm) {
//         if (frm.doc.amount_commitment) {
//             frm.set_value("copy_commitment", 0); // uncheck other
//         }
//         frm.trigger("toggle_commitment_mode");
//     },

//     toggle_commitment_mode(frm) {
//         if (frm.doc.copy_commitment) {
//             frm.set_df_property("comm_copies_pm", "read_only", 0);
//             frm.set_df_property("comm_rate_pc", "read_only", 0);
//             frm.set_df_property("comm_amt_pm", "read_only", 1);
//             frm.trigger("calculate_committed_amount");
//         } else if (frm.doc.amount_commitment) {
//             frm.set_df_property("comm_copies_pm", "read_only", 1);
//             frm.set_df_property("comm_rate_pc", "read_only", 1);
//             frm.set_df_property("comm_amt_pm", "read_only", 0);
//             frm.set_value("comm_copies_pm", 0);
//             frm.set_value("comm_rate_pc", 0);
//         } else {
//             // neither selected → everything editable
//             frm.set_df_property("comm_copies_pm", "read_only", 1);
//             frm.set_df_property("comm_rate_pc", "read_only", 1);
//             frm.set_df_property("comm_amt_pm", "read_only", 1);
//         }
//     }
// });